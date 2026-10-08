#!/usr/bin/env python3
"""Cargo pay for the merged Jazzycat cargo, measured the way DriveDogs Economy measures it.

A job pays unit_reward_per_km x units per trailer load; units come from the cargo's trailer_defs (volume and
payload). Economy balances pay per load against vanilla's median load (Economy ADR-0001), so this tool imports
Economy's own rules and units maths from the Economy repo (host root `@drivedogs_economy`,
tools/generate_cargo_variety.py) instead of copying them. Economy stays standalone; this pack requires it.

    python tools/cargo_rebalance.py analyze     -> cargo/analysis.md, cargo/analysis.tsv (Jazzycat as shipped)
    python tools/cargo_rebalance.py generate    -> cargo/edits.yaml (megapack base_edits), cargo/rebalance.md

`generate` applies the hand-reviewed data fixes in cargo/fixes.yaml, then moves each rebalanced group's median pay
per load to its target (docs/adr/ADR-0002-cargo-pay-follows-economy.md). Neither command touches the sources.
"""
import argparse
import csv
import importlib.util
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path.home() / ".agent-brains" / "profiles" / "scs-mod-developer" / "skills" / "megapack" / "scripts"))
from megapack import megapack_root, reference_root, repo_game  # noqa: E402  — the host config API
GAME = repo_game(ROOT)  # megapack.yaml package.game
OUT_DIR = ROOT / "cargo"
ECONOMY_SYMBOLS = ("HAZMAT_TARGETS", "LOAD_CAP", "VEHICLE_CARRIER_TARGET", "load_trailers", "load_vanilla", "field")

CARGO_RE = re.compile(r"^\s*cargo_data\s*:\s*cargo\.(\S+)", re.MULTILINE)
RATE_RE = re.compile(r"^\s*unit_reward_per_km\s*:\s*([\d.]+)", re.MULTILINE)
LIST_RE = {k: re.compile(rf"^\s*{re.escape(k)}\[\]\s*:\s*(\S+)", re.MULTILINE) for k in ("body_types", "group")}


# ---------------------------------------------------------------- host + config
def load_economy():
    path = megapack_root(GAME, "drivedogs_economy") / "tools" / "generate_cargo_variety.py"
    if not path.is_file():
        raise SystemExit(f"DriveDogs Economy generator not found: {path}")
    spec = importlib.util.spec_from_file_location("dde_cargo_variety", path)
    econ = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(econ)
    missing = [s for s in ECONOMY_SYMBOLS if not hasattr(econ, s)]
    if missing:
        raise SystemExit(f"{path} no longer defines {', '.join(missing)}: update this tool to Economy's new rules")
    return econ, path


def sources_in_layer_order(ref_root: Path) -> list[tuple[str, Path]]:
    raw = yaml.safe_load((ROOT / "sources.yaml").read_text(encoding="utf-8"))["sources"]
    out = []
    for s in sorted(raw, key=lambda s: int(s.get("layer", 10))):
        d = ref_root / "local" / s["id"] / str(s["version"])
        if not d.is_dir():
            raise SystemExit(f"{s['id']} {s['version']} not extracted at {d}")
        out.append((s["id"], d))
    return out


# ---------------------------------------------------------------- parsing
def parse_cargo(text: str, econ) -> dict | None:
    m = CARGO_RE.search(text)
    if not m:
        return None
    f = lambda k, d=None: econ.field(text, k, d)
    return {
        "id": m.group(1), "rate": float(RATE_RE.search(text).group(1)),
        "mass": float(f("mass", 0)), "volume": float(f("volume", 1)) or 1.0,
        "bodies": LIST_RE["body_types"].findall(text), "groups": LIST_RE["group"].findall(text),
        "adr": f("adr_class"), "valuable": f("valuable") == "true", "overweight": f("overweight") == "true",
        "fragility": float(f("fragility", 0) or 0), "prob_coef": f("prob_coef"),
    }


def units(entry: dict, trailers: list[dict]) -> tuple[list[int], bool]:
    """Economy's units_per_load, returning every single-trailer count and whether payload (not volume) limits
    them all. Unlike Economy's function, a trailer_def that cannot take even one unit is skipped (the game never
    assigns it): Economy counts it as 0 units, which zeroes 30 vanilla heavy cargoes (1 unit of 70-90 volume vs a
    60-volume lowboy) and puts its anchor median at 19.87 instead of 20.06."""
    fits = [t for t in trailers if t["body"] in entry["bodies"] and t["owner"] in (None, entry["id"])]
    singles = [t for t in fits if t["chain"] == "single"] or fits
    counts, by_mass = [], []
    for t in singles:
        u = t["volume"] / entry["volume"]
        m = t["payload"] / entry["mass"] if entry["mass"] > 0 and t["payload"] > 0 else u
        if int(min(u, m)) < 1:
            continue
        counts.append(int(min(u, m)))
        by_mass.append(m < u)
    return counts, bool(by_mass) and all(by_mass)


# ---------------------------------------------------------------- analysis
def category(c: dict) -> list[str]:
    cats = []
    if c["adr"] or "adr" in c["groups"]:
        cats.append(f"ADR class {c['adr']}" if c["adr"] else "ADR (group only, no class)")
    if c["overweight"]:
        cats.append("overweight")
    if c["valuable"]:
        cats.append("valuable")
    if c["fragility"] >= 0.7:
        cats.append("fragile (>=0.7)")
    return cats or ["ordinary"]


def stats(loads: list[float], median_load: float) -> str:
    if not loads:
        return "| 0 | | | | |"
    s = sorted(loads)
    q = statistics.quantiles(s, n=10) if len(s) > 1 else [s[0]] * 9
    return f"| {len(s)} | {q[0]:.1f} | {statistics.median(s):.1f} | {q[8]:.1f} | {statistics.median(s) / median_load:.2f}x |"


def load_trailer_defs(def_dir: Path, econ) -> list[dict]:
    """Economy's load_trailers (same fields and payload formula), plus unit name, file and the weights a fix may
    change, so cargo/fixes.yaml can be applied before pay is computed."""
    paths = [(p, None) for p in (def_dir / "vehicle" / "trailer_defs").glob("*.sii")]
    paths += [(p, p.parent.name) for p in (def_dir / "cargo").glob("*/*.sii")]
    out = []
    for path, owner in paths:
        text = path.read_text(encoding="utf-8-sig")
        body, volume = econ.field(text, "body_type"), econ.field(text, "volume")
        if not body or not volume:
            continue
        m = re.search(r"^\s*trailer_def\s*:\s*(\S+)", text, re.MULTILINE)
        t = {"owner": owner, "body": body, "volume": float(volume), "chain": econ.field(text, "chain_type", "single"),
             "gross": float(econ.field(text, "gross_trailer_weight_limit", 0)),
             "chassis": float(econ.field(text, "chassis_mass", 0)), "body_mass": float(econ.field(text, "body_mass", 0)),
             "unit": m.group(1) if m else None}
        t["payload"] = t["gross"] - t["chassis"] - t["body_mass"]
        out.append(t)
    return out


def load_model(econ) -> dict:
    mp = yaml.safe_load((ROOT / "megapack.yaml").read_text(encoding="utf-8"))
    ref_root = reference_root(GAME)
    version = str(mp["base_game"]["version"])
    base_def = ref_root / "base" / version / "def"
    known_companies = {p.name.lower() for p in (base_def / "company").iterdir() if p.is_dir()}

    # Economy's anchor, computed by Economy's own code (so targets stay aligned with Economy even where its maths
    # differs from units() below)
    vanilla = econ.load_vanilla(base_def)
    median_load = statistics.median(c["load"] for c in vanilla.values())

    # vanilla by the same attributes, for "what does vanilla pay for this kind of cargo"
    v_trailers = econ.load_trailers(base_def)
    v_rows = []
    for path in (base_def / "cargo").glob("*.sui"):
        c = parse_cargo(path.read_text(encoding="utf-8-sig"), econ)
        if c:
            n, _ = units(c, v_trailers)
            if n:
                v_rows.append({**c, "load": c["rate"] * statistics.median(n)})

    # merged Jazzycat view: sources in layer order, later layer wins per path (the lock has no collisions)
    cargo_files, trailers, links, included = {}, list(v_trailers), defaultdict(Counter), set()
    for sid, root in sources_in_layer_order(ref_root):
        d = root / "def"
        for p in (d / "cargo").glob("*.sui"):
            cargo_files[p.name.lower()] = (sid, p.relative_to(root).as_posix(), p)
        trailers += load_trailer_defs(d, econ)
        for p in d.glob("cargo.*.sii"):
            included |= {Path(i).name.lower() for i in re.findall(r'@include\s+"([^"]+)"', p.read_text(encoding="utf-8-sig"))}
        for p in (d / "company").glob("*/*/*.sii"):
            company, direction = p.parent.parent.name.lower(), p.parent.name.lower()
            if company in known_companies:
                links[p.stem.lower()][direction] += 1

    cargo = []
    for name, (sid, rel, p) in sorted(cargo_files.items()):
        c = parse_cargo(p.read_text(encoding="utf-8-sig"), econ)
        if c:
            cargo.append({"source": sid, "rel": rel, "c": c, "included": name in included,
                          "senders": links[c["id"].lower()]["out"], "receivers": links[c["id"].lower()]["in"]})
    return {"version": version, "vanilla_n": len(vanilla), "median_load": median_load, "v_rows": v_rows,
            "trailers": trailers, "cargo": cargo}


def rows_for(model: dict) -> list[dict]:
    median_load, rows = model["median_load"], []
    for e in model["cargo"]:
        c = e["c"]
        n, mass_limited = units(c, model["trailers"])
        u = statistics.median(n) if n else 0
        load = c["rate"] * u
        rows.append({
            "source": e["source"], "cargo": c["id"], "rate": c["rate"], "mass": c["mass"], "volume": c["volume"],
            "units": u, "units_min": min(n) if n else 0, "units_max": max(n) if n else 0,
            "mass_limited": mass_limited, "load": round(load, 2), "x_median": round(load / median_load, 2),
            "category": "; ".join(category(c)), "groups": ",".join(c["groups"]), "adr": c["adr"] or "",
            "valuable": c["valuable"], "overweight": c["overweight"], "fragility": c["fragility"],
            "included": e["included"], "senders": e["senders"], "receivers": e["receivers"],
            "offered": e["included"] and u > 0 and e["senders"] > 0, "rel": e["rel"],
        })
    return rows


def analyze(args) -> None:
    econ, econ_path = load_economy()
    model = load_model(econ)
    version, median_load, v_rows = model["version"], model["median_load"], model["v_rows"]
    vanilla = range(model["vanilla_n"])
    rows = rows_for(model)

    OUT_DIR.mkdir(exist_ok=True)
    with open(OUT_DIR / "analysis.tsv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, list(rows[0]), delimiter="\t", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)

    live = [r for r in rows if r["offered"]]
    md = [
        "# Cargo pay analysis (generated by `tools/cargo_rebalance.py analyze`)", "",
        f"Rules and units maths: `{econ_path}` (HAZMAT_TARGETS {econ.HAZMAT_TARGETS}, "
        f"VEHICLE_CARRIER_TARGET {econ.VEHICLE_CARRIER_TARGET}, LOAD_CAP {econ.LOAD_CAP}).",
        f"Vanilla {version}: {len(vanilla)} cargoes, median load **{median_load:.2f} EUR/km** (Economy's anchor).",
        f"Jazzycat: {len(rows)} cargoes, **{len(live)} offered** (included, carried by a trailer_def, sent by at least "
        "one base-game company). Pay per load = rate x median units per single trailer.", "",
        "## Pay per load: Jazzycat vs vanilla for the same kind of cargo", "",
        "| category | Jazzycat n | p10 | median | p90 | x median | vanilla n | p10 | median | p90 | x median |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    cats = sorted({k for r in live for k in r["category"].split("; ")} | {k for v in v_rows for k in category(v)})
    for k in ["ordinary"] + [k for k in cats if k != "ordinary"]:
        j = [r["load"] for r in live if k in r["category"].split("; ")]
        v = [x["load"] for x in v_rows if k in category(x)]
        md.append(f"| {k} " + stats(j, median_load) + stats(v, median_load)[1:])
    md += ["", "## By cargo group", "",
           "| group | Jazzycat n | p10 | median | p90 | x median | vanilla n | p10 | median | p90 | x median |",
           "|---|---|---|---|---|---|---|---|---|---|---|"]
    groups = Counter(g for r in live for g in (r["groups"] or "none").split(","))
    for g, _ in groups.most_common():
        j = [r["load"] for r in live if g in (r["groups"] or "none").split(",")]
        v = [x["load"] for x in v_rows if g in (x["groups"] or ["none"])]
        md.append(f"| {g} " + stats(j, median_load) + stats(v, median_load)[1:])

    md += ["", "## Economy's rules applied as they are", ""]
    by_class = defaultdict(list)
    for r in live:
        if r["adr"]:
            by_class[r["adr"]].append(r["load"])
    for cls, target in econ.HAZMAT_TARGETS.items():
        ls = by_class.get(cls, [])
        md.append(f"- ADR class {cls}: target {target}x median load ({target * median_load:.1f} EUR/km); "
                  f"Jazzycat has {len(ls)}" + (f", median {statistics.median(ls):.1f}" if ls else ""))
    group_only = [r for r in live if not r["adr"] and "adr" in r["groups"].split(",")]
    md.append(f"- `group[]: adr` without a class: {len(group_only)} (no Economy tier; the maintainer counts them as hazardous)")
    md.append(f"- Cap {econ.LOAD_CAP}x median ({econ.LOAD_CAP * median_load:.1f} EUR/km): "
              f"{sum(r['x_median'] > econ.LOAD_CAP for r in live)} Jazzycat cargoes above it")

    md += ["", "## Problems", ""]
    md.append(f"- Payload-limited (fewer units than the trailer volume allows): "
              f"{sum(r['mass_limited'] for r in live)}")
    worst = sorted((r for r in live if r["x_median"] < 0.75), key=lambda r: r["load"])
    md.append(f"- Paying under 0.75x median: {len(worst)}")
    for r in worst[:15]:
        md.append(f"  - `{r['cargo']}` ({r['source']}): {r['units']} units x {r['rate']} = {r['load']} EUR/km "
                  f"({r['x_median']}x), mass {r['mass']} kg/unit, {r['category']}")
    for label, cond in (("Not included by any def/cargo.*.sii", lambda r: not r["included"]),
                        ("No trailer_def carries it", lambda r: r["included"] and not r["units"]),
                        ("No base-game company sends it (map-mod only)",
                         lambda r: r["included"] and r["units"] and not r["senders"])):
        bad = [r["cargo"] for r in rows if cond(r)]
        md.append(f"- {label}: {len(bad)}" + (f" — {', '.join(bad[:12])}" + (" …" if len(bad) > 12 else "") if bad else ""))
    spread = [r for r in live if r["units_min"] and r["units_max"] > 1.5 * r["units_min"]]
    md.append(f"- Units vary >1.5x between a cargo's own trailers: {len(spread)}")
    (OUT_DIR / "analysis.md").write_text("\n".join(md) + "\n", encoding="utf-8", newline="\n")
    print("\n".join(md))


# ---------------------------------------------------------------- generate
CARGO_KEYS = {"mass": "mass", "volume": "volume", "unit_reward_per_km": "rate", "body_types[]": "bodies"}
TRAILER_KEYS = {"gross_trailer_weight_limit": "gross", "chassis_mass": "chassis", "body_mass": "body_mass",
                "volume": "volume", "body_type": "body"}


def apply_fixes(model: dict, fixes: dict) -> None:
    """Apply cargo/fixes.yaml `set` ops to the in-memory model, so pay is computed on the fixed data."""
    by_cargo = {("cargo." + e["c"]["id"]).lower(): e["c"] for e in model["cargo"]}
    by_trailer = {t["unit"].lower(): t for t in model["trailers"] if t.get("unit")}
    for rel, per_unit in fixes.items():
        for unit, ops in per_unit.items():
            extra = set(ops) - {"set"}
            if extra:
                raise SystemExit(f"fixes.yaml {rel} {unit}: only `set` is supported here, not {sorted(extra)}")
            kind, target = (CARGO_KEYS, by_cargo.get(unit.lower())) if unit.startswith("cargo.") \
                else (TRAILER_KEYS, by_trailer.get(unit.lower()))
            if target is None:
                raise SystemExit(f"fixes.yaml {rel}: no unit {unit} in the merged sources")
            for key, value in ops["set"].items():
                if key not in kind:
                    raise SystemExit(f"fixes.yaml {rel} {unit}: `{key}` is not a key this tool models")
                target[kind[key]] = list(value) if isinstance(value, list) else (
                    value if isinstance(value, str) else float(value))
            if unit.startswith("trailer_def."):
                target["payload"] = target["gross"] - target["chassis"] - target["body_mass"]


def targets(model: dict, econ) -> dict[str, tuple[float, str]]:
    """Pay per load, as a multiple of Economy's anchor, for each group this pack rebalances (ADR-0002): what that
    kind of cargo pays with DriveDogs Economy installed. Economy's own target where it has one (hazmat tiers),
    else vanilla's own per-load median for the same kind of cargo (Economy leaves those at vanilla)."""
    median_load, v_rows = model["median_load"], model["v_rows"]

    def vanilla_x(pred) -> float:
        loads = [r["load"] for r in v_rows if pred(r)]
        return statistics.median(loads) / median_load

    out = {}
    for cls in sorted({r["adr"] for r in v_rows if r["adr"]} | {e["c"]["adr"] for e in model["cargo"] if e["c"]["adr"]}):
        if cls in econ.HAZMAT_TARGETS:
            out[f"ADR class {cls}"] = (econ.HAZMAT_TARGETS[cls], f"Economy hazmat tier for class {cls}")
        elif any(r["adr"] == cls for r in v_rows):
            out[f"ADR class {cls}"] = (vanilla_x(lambda r: r["adr"] == cls),
                                       f"vanilla class {cls} (Economy keeps vanilla's premium)")
    out["overweight"] = (vanilla_x(lambda r: r["overweight"]), "vanilla overweight (heavy/oversize) cargo")
    out["bulk"] = (vanilla_x(lambda r: "bulk" in r["groups"]), "vanilla bulk cargo")
    return out


def group_of(r: dict, tgt: dict) -> str | None:
    """Premiums never stack: the highest applicable premium wins; bulk (a discount) only applies without one."""
    premiums = [k for k in (f"ADR class {r['adr']}" if r["adr"] else None, "overweight" if r["overweight"] else None)
                if k in tgt]
    if premiums:
        return max(premiums, key=lambda k: tgt[k][0])
    return "bulk" if "bulk" in r["groups"].split(",") else None


def yaml_value(v) -> str:
    if isinstance(v, list):
        return "[" + ", ".join(str(x) for x in v) + "]"
    return str(v)


def economy_commit(econ_path: Path) -> str:
    import subprocess
    r = subprocess.run(["git", "-C", str(econ_path.parent), "rev-parse", "--short", "HEAD"], capture_output=True, text=True)
    return r.stdout.strip() or "unknown"


def generate(args) -> None:
    econ, econ_path = load_economy()
    model = load_model(econ)
    fixes_path = OUT_DIR / "fixes.yaml"
    fixes = yaml.safe_load(fixes_path.read_text(encoding="utf-8")) or {}
    before = {r["cargo"]: r for r in rows_for(model)}
    apply_fixes(model, fixes)
    rows = rows_for(model)
    median_load, cap_x = model["median_load"], econ.LOAD_CAP
    tgt = targets(model, econ)

    groups = defaultdict(list)
    for r in rows:
        g = group_of(r, tgt) if r["offered"] else None
        if g:
            groups[g].append(r)

    changes = {}  # cargo id -> (new rate, comment)
    summary = []
    for g, members in sorted(groups.items()):
        target_x, why = tgt[g]
        scale = target_x * median_load / statistics.median(r["load"] for r in members)
        new_loads = []
        for r in members:
            rate = r["rate"] * scale
            rate = min(rate, cap_x * median_load / r["units"])
            if g != "bulk":
                rate = max(rate, r["rate"])  # a premium never lowers pay (Economy rule)
            rate = round(rate, 4)
            new_loads.append(rate * r["units"])
            if rate != r["rate"]:
                changes[r["cargo"]] = (rate, f"{g} -> {target_x:.2f}x median ({why}): "
                                             f"{r['load']:.1f} -> {rate * r['units']:.1f} EUR/km per load, rate {r['rate']} -> {rate}")
        summary.append(f"| {g} | {len(members)} | {statistics.median(r['load'] for r in members):.1f} | "
                       f"{statistics.median(new_loads):.1f} | {target_x:.2f}x | {why} |")

    # edits: fixes first (as written), then the rate changes; one entry per unit
    edits = defaultdict(dict)  # rel -> unit -> (set dict, [comments])
    for rel, per_unit in fixes.items():
        for unit, ops in per_unit.items():
            edits[rel][unit] = (dict(ops["set"]), ["fix: see cargo/fixes.yaml"])
    by_id = {r["cargo"]: r for r in rows}
    for cid, (rate, comment) in changes.items():
        rel, unit = by_id[cid]["rel"], f"cargo.{cid}"
        sets, notes = edits[rel].get(unit, ({}, []))
        sets["unit_reward_per_km"] = rate
        edits[rel][unit] = (sets, notes + [comment])

    lines = [
        "# GENERATED by `python tools/cargo_rebalance.py generate` - do not edit. Change cargo/fixes.yaml or the tool.",
        f"# Economy rules: {econ_path} @ {economy_commit(econ_path)}; anchor = vanilla {model['version']} median load "
        f"{median_load:.2f} EUR/km (Economy's maths). Cap {cap_x}x median. See docs/adr/ADR-0002-cargo-pay-follows-economy.md.",
    ]
    for rel in sorted(edits, key=str.lower):
        lines.append(f"{rel}:")
        for unit, (sets, notes) in edits[rel].items():
            lines.append(f"  {unit}:")
            lines += [f"    # {n}" for n in notes]
            lines.append("    set:")
            lines += [f"      {k}: {yaml_value(v)}" for k, v in sets.items()]
    (OUT_DIR / "edits.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")

    fixed = [r for r in rows if r["cargo"] in before and r["load"] != before[r["cargo"]]["load"]
             and r["cargo"] not in changes]
    md = ["# Cargo rebalance (generated by `tools/cargo_rebalance.py generate`)", "",
          f"Economy `{econ_path.name}` @ {economy_commit(econ_path)}; anchor {median_load:.2f} EUR/km per load. "
          f"{len(changes)} rate changes, {sum(len(u) for u in fixes.values())} fixes; `cargo/edits.yaml` holds both.", "",
          "| group | cargoes | median load before | after | target | why |", "|---|---|---|---|---|---|", *summary, "",
          "Fixed data (pay changes through units, rate unchanged):", ""]
    md += [f"- `{r['cargo']}`: {before[r['cargo']]['units']} -> {r['units']} units, "
           f"{before[r['cargo']]['load']} -> {r['load']} EUR/km per load" for r in fixed]
    (OUT_DIR / "rebalance.md").write_text("\n".join(md) + "\n", encoding="utf-8", newline="\n")
    print("\n".join(md))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("analyze", help="write cargo/analysis.md and cargo/analysis.tsv")
    sub.add_parser("generate", help="apply cargo/fixes.yaml, rebalance rates; write cargo/edits.yaml and cargo/rebalance.md")
    args = ap.parse_args()
    {"analyze": analyze, "generate": generate}[args.cmd](args)


if __name__ == "__main__":
    main()
