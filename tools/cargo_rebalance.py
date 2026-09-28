#!/usr/bin/env python3
"""Cargo pay for the merged Jazzycat cargo, measured the way DriveDogs Economy measures it.

A job pays unit_reward_per_km x units per trailer load; units come from the cargo's trailer_defs (volume and
payload). Economy balances pay per load against vanilla's median load (Economy ADR-0001), so this tool imports
Economy's own rules and units maths from the Economy repo (host root `@drivedogs_economy`,
tools/generate_cargo_variety.py) instead of copying them. Economy stays standalone; this pack requires it.

    python tools/cargo_rebalance.py analyze     -> cargo/analysis.md, cargo/analysis.tsv

Read-only: nothing under src/ or the sources is touched.
"""
import argparse
import csv
import importlib.util
import re
import socket
import statistics
from collections import Counter, defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
HOSTS_DIR = Path.home() / ".agent-brains" / "profiles" / "ets2-mod-developer" / "hosts"
OUT_DIR = ROOT / "cargo"
ECONOMY_SYMBOLS = ("HAZMAT_TARGETS", "LOAD_CAP", "VEHICLE_CARRIER_TARGET", "load_trailers", "load_vanilla", "field")

CARGO_RE = re.compile(r"^\s*cargo_data\s*:\s*cargo\.(\S+)", re.MULTILINE)
RATE_RE = re.compile(r"^\s*unit_reward_per_km\s*:\s*([\d.]+)", re.MULTILINE)
LIST_RE = {k: re.compile(rf"^\s*{re.escape(k)}\[\]\s*:\s*(\S+)", re.MULTILINE) for k in ("body_types", "group")}


# ---------------------------------------------------------------- host + config
def host_section(heading: str) -> dict[str, str]:
    host = socket.gethostname().lower()
    files = [p for p in HOSTS_DIR.glob("*.local.md") if p.name.lower() == f"{host}.local.md"]
    if not files:
        raise SystemExit(f"no host file for {host} in {HOSTS_DIR}")
    entries, inside = {}, False
    for line in files[0].read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("## "):
            inside = line[3:].strip().lower() == heading.lower()
        elif inside and line.startswith("- ") and ":" in line:
            k, v = line[2:].split(":", 1)
            entries[k.strip()] = v.split("<!--", 1)[0].strip()
    return entries


def load_economy():
    root = host_section("MegaPack Roots").get("drivedogs_economy")
    if not root:
        raise SystemExit("host file has no '- drivedogs_economy:' under '## MegaPack Roots'")
    path = Path(root) / "tools" / "generate_cargo_variety.py"
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


def analyze(args) -> None:
    econ, econ_path = load_economy()
    mp = yaml.safe_load((ROOT / "megapack.yaml").read_text(encoding="utf-8"))
    ref_root = Path(host_section("Extracted Reference Root")["root"])
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
            cargo_files[p.name.lower()] = (sid, p)
        trailers += econ.load_trailers(d)
        for p in d.glob("cargo.*.sii"):
            included |= {Path(i).name.lower() for i in re.findall(r'@include\s+"([^"]+)"', p.read_text(encoding="utf-8-sig"))}
        for p in (d / "company").glob("*/*/*.sii"):
            company, direction = p.parent.parent.name.lower(), p.parent.name.lower()
            if company in known_companies:
                links[p.stem.lower()][direction] += 1

    rows = []
    for name, (sid, p) in sorted(cargo_files.items()):
        c = parse_cargo(p.read_text(encoding="utf-8-sig"), econ)
        if not c:
            continue
        n, mass_limited = units(c, trailers)
        u = statistics.median(n) if n else 0
        load = c["rate"] * u
        offered = name in included and u > 0 and links[c["id"].lower()]["out"] > 0
        rows.append({
            "source": sid, "cargo": c["id"], "rate": c["rate"], "mass": c["mass"], "volume": c["volume"],
            "units": u, "units_min": min(n) if n else 0, "units_max": max(n) if n else 0,
            "mass_limited": mass_limited, "load": round(load, 2), "x_median": round(load / median_load, 2),
            "category": "; ".join(category(c)), "groups": ",".join(c["groups"]), "adr": c["adr"] or "",
            "valuable": c["valuable"], "overweight": c["overweight"], "fragility": c["fragility"],
            "included": name in included, "senders": links[c["id"].lower()]["out"],
            "receivers": links[c["id"].lower()]["in"], "offered": offered,
        })

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


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("analyze", help="write cargo/analysis.md and cargo/analysis.tsv")
    args = ap.parse_args()
    {"analyze": analyze}[args.cmd](args)


if __name__ == "__main__":
    main()
