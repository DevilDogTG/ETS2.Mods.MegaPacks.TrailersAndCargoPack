#!/usr/bin/env python3
"""Keep Jazzycat cargo out of the company slots ETS2 achievements check.

Some achievements count only a vanilla cargo delivered from or to one company (Volvo Trucks Lover: Volvo Trucks from
the Volvo Truck Factory). A Jazzycat cargo linked to that company looks the same in the job list and delivery log but
does not count, and it makes the vanilla job rarer (docs/adr/ADR-0003-achievement-company-slots-stay-vanilla.md).
This tool reads the base game's def/achievements*.sii, resolves every achievement that filters by cargo and company to
its slots (company, in|out) and checks each pack cargo link at those slots:

    python tools/achievement_guard.py           -> cargo/achievements.md (report)
    python tools/achievement_guard.py --check   -> no report; exit 1 on any problem

A link is decided when megapack.yaml `exclude` drops it, or cargo/achievements.yaml `keep` lists it with a reason.
An undecided link (new after a Jazzycat or game update), a stale `keep` entry, a pack cargo definition that replaces
a cargo an achievement names, or a pack cargo named like the cargo of an achievement without a company (counted
wherever it is loaded) that a merged link offers is a problem: decide it with the maintainer, then exclude or keep it.
A link file holds only `cargo:`, no city, so it applies to the company in every city that has one.
"""
import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

import yaml

from cargo_rebalance import GAME, ROOT, base_dir, reference_root
from megapack import excluded, load_config  # noqa: E402  — on sys.path via cargo_rebalance

CONFIG = ROOT / "cargo" / "achievements.yaml"
REPORT = ROOT / "cargo" / "achievements.md"
UNIT_RE = re.compile(r"^\s*(\w+)\s*:\s*([.\w]+)\s*\{(.*?)^\s*\}", re.MULTILINE | re.DOTALL)
FIELD_RE = re.compile(r"^\s*(\w+)(?:\[\])?\s*:\s*(.*?)\s*$", re.MULTILINE)
LINK_CARGO_RE = re.compile(r'^\s*cargo\s*:\s*"?([^"\s]*)"?', re.MULTILINE)
NAME_RE = re.compile(r'^\s*name\s*:\s*"([^"]*)"', re.MULTILINE)
LOCK_LINK_RE = re.compile(r"^(def/company/[^/\t]+/(?:in|out)/([^/.\t]+)[^/\t]*\.sii)\t", re.MULTILINE)
LOCALE_RE = re.compile(r'key\[\]\s*:\s*"([^"]+)"\s*val\[\]\s*:\s*"([^"]*)"')
ROLE_DIR = {"source": "out", "target": "in"}
# Flat achievement units: company.city lists and the slot direction they check.
FLAT_COMPANIES = {"targets": "in", "target_companies": "in", "sources": "out", "source_companies": "out"}


# ---------------------------------------------------------------- SII
def strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return "\n".join(re.split(r"#|//", line, maxsplit=1)[0] for line in text.splitlines())


def read_units(paths) -> dict[str, tuple[str, dict[str, list[str]], str]]:
    """Unit name -> (unit type, fields (every value a list), file name)."""
    out = {}
    for p in paths:
        for typ, name, body in UNIT_RE.findall(strip_comments(p.read_text(encoding="utf-8-sig"))):
            fields = defaultdict(list)
            for k, v in FIELD_RE.findall(body):
                fields[k].append(v.strip('"'))
            out[name] = (typ, dict(fields), p.name)
    return out


# ---------------------------------------------------------------- achievements
def dnf(units: dict, name: str) -> list[dict]:
    """A nested delivery condition as alternatives (OR) of single-delivery requirements (AND):
    {"cargos": set | None (any), "companies": [(company, role, place)], "places": [str]}."""
    typ, f, _ = units[name]
    if typ in ("achievement_delivery", "achievement_delivery_count"):
        return dnf(units, f["condition"][0])
    if typ in ("achievement_delivery_any", "achievement_delivery_sequence"):  # each item is its own delivery
        return [r for child in f.get("list", []) for r in dnf(units, child)]
    if typ == "achievement_delivery_each":  # one delivery meets every item
        reqs = [{"cargos": None, "companies": [], "places": []}]
        for child in f.get("list", []):
            reqs = [and_req(a, b) for a in reqs for b in dnf(units, child)]
        return reqs
    req = {"cargos": None, "companies": [], "places": []}
    if typ == "achievement_delivery_cargo":
        if "cargo_name" in f:  # `adr:` instead: any cargo of that ADR class counts, the pack's too
            req["cargos"] = {f["cargo_name"][0].lower()}
    elif typ == "achievement_delivery_company":
        place = (f.get("city_name") or f.get("country_name") or ["any city"])[0]
        req["companies"].append((f["company_name"][0].lower(), f["role"][0], place))
    elif typ != "achievement_delivery_not":  # a NOT never asks for a cargo at a company; other leaves: place, damage
        req["places"] += [f"{k} {v[0]}" for k, v in f.items() if k.endswith(("city_name", "country_name"))]
    return [req]


def and_req(a: dict, b: dict) -> dict:
    cargos = b["cargos"] if a["cargos"] is None else a["cargos"] if b["cargos"] is None else a["cargos"] & b["cargos"]
    return {"cargos": cargos, "companies": a["companies"] + b["companies"], "places": a["places"] + b["places"]}


def achievements(units: dict) -> list[dict]:
    """Every achievement that names cargo: id, file, requirements."""
    out = []
    for name, (typ, f, file) in units.items():
        if "achievement_name" not in f:
            continue
        if "condition" in f:
            reqs = dnf(units, name)
        else:
            cargos = {c.lower() for c in f.get("cargos", []) + f.get("cargo", [])} or None
            companies = [(c.split(".")[0].lower(), "source" if d == "out" else "target", c.split(".")[1])
                         for k, d in FLAT_COMPANIES.items() for c in f.get(k, []) if "." in c]
            places = [f"{k} {c}" for k in ("source_cities", "target_cities") for c in f.get(k, [])]
            reqs = [{"cargos": cargos, "companies": companies, "places": places}]
        reqs = [r for r in reqs if r["cargos"]]  # only a cargo filter can be fooled by a look-alike
        if reqs:
            out.append({"id": f["achievement_name"][0], "file": file, "reqs": reqs})
    return sorted(out, key=lambda a: a["id"])


def slots(achs: list[dict]) -> dict[tuple[str, str], list[dict]]:
    """(company, in|out) -> what each achievement checks there: id, cargos, places."""
    out = defaultdict(list)
    for a in achs:
        for r in a["reqs"]:
            for company, role, place in r["companies"]:
                key = (company, ROLE_DIR[role])
                entry = next((e for e in out[key] if e["id"] == a["id"]), None)
                if entry is None:
                    entry = {"id": a["id"], "file": a["file"], "cargos": set(), "places": set()}
                    out[key].append(entry)
                entry["cargos"] |= r["cargos"]
                entry["places"].add(place)
    return dict(out)


# ---------------------------------------------------------------- pack
def pack_links(cfg, wanted: set[tuple[str, str]]) -> dict[tuple[str, str], list[dict]]:
    """Every pack cargo link at the wanted slots, excluded or not, as each source ships it."""
    out = defaultdict(list)
    for s in sorted(cfg.sources, key=lambda s: s.layer):
        root = cfg.source_dir(s)
        for company, direction in sorted(wanted):
            for p in sorted((root / "def" / "company" / company / direction).glob("*.sii")):
                rel = s.rename(p.relative_to(root).as_posix())
                m = LINK_CARGO_RE.search(p.read_text(encoding="utf-8-sig", errors="replace"))
                cargo = m.group(1).removeprefix("cargo.").lower() if m else ""
                hit = next((x for x in cfg.excludes_for(s) if excluded(rel, [x])), None)
                out[(company, direction)].append(
                    {"source": s.id, "name": p.name.removesuffix(".sii"), "path": rel, "cargo": cargo, "exclude": hit})
    return dict(out)


def cargo_names(cfg, base: Path) -> tuple[dict[str, str], dict[str, str]]:
    """cargo id -> display name (base game, then the pack's later layers), and pack cargo id -> merged path."""
    locale = {}
    for root in [base] + [cfg.source_dir(s) for s in sorted(cfg.sources, key=lambda s: s.layer)]:
        for p in sorted((root / "locale" / "en_us").glob("*.s[iu]i")):
            locale.update(LOCALE_RE.findall(p.read_text(encoding="utf-8-sig", errors="replace")))
    names, pack = {}, {}

    def read(path: Path, cid: str):
        m = NAME_RE.search(path.read_text(encoding="utf-8-sig", errors="replace"))
        if m:
            raw = m.group(1)
            names[cid] = re.sub(r"@@(\w+)@@", lambda k: locale.get(k.group(1), k.group(0)), raw)

    for p in (base / "def" / "cargo").glob("*.sui"):
        read(p, p.name.split(".")[0].lower())
    for s in sorted(cfg.sources, key=lambda s: s.layer):
        root = cfg.source_dir(s)
        for p in (root / "def" / "cargo").glob("*.sui"):
            rel = s.rename(p.relative_to(root).as_posix())
            if not excluded(rel, cfg.excludes_for(s)):
                cid = p.name.split(".")[0].lower()
                read(p, cid)
                pack[cid] = rel
    edits_path = (cfg.megapack.get("base_edits") or {}).get("edits")
    edits = yaml.safe_load((ROOT / edits_path).read_text(encoding="utf-8")) if edits_path else {}
    for rel, per_unit in (edits or {}).items():  # the build's renames (cargo/fixes.yaml -> edits.yaml)
        for unit, ops in per_unit.items():
            name = (ops.get("set") or {}).get("name")
            if unit.startswith("cargo.") and name is not None:
                names[unit.removeprefix("cargo.").lower()] = str(name).strip('"')
    return names, pack


def lookalikes(cfg, achs: list[dict], names: dict, pack_cargo: dict) -> list[dict]:
    """Pack cargoes named like a cargo that an achievement without a company counts (wherever it is loaded), with the
    merged links that offer them. The lock lists the merged files; a link is named after its cargo (as Jazzycat
    ships them), so its file name finds it without reading 70k link files."""
    by_name = defaultdict(list)
    for cid in pack_cargo:
        if cid in names:
            by_name[names[cid].strip().lower()].append(cid)
    linked = defaultdict(list)
    for s in cfg.sources:
        for m in LOCK_LINK_RE.finditer(cfg.lock_file(s).read_text(encoding="utf-8")):
            linked[m.group(2).lower()].append(m.group(1))
    out = []
    for a in achs:
        if any(r["companies"] for r in a["reqs"]):
            continue
        for cid in sorted({c for r in a["reqs"] for c in r["cargos"]}):
            for pid in by_name.get(names.get(cid, "").strip().lower(), []):
                if pid != cid:
                    out.append({"id": a["id"], "cargo": cid, "pack": pid, "links": sorted(set(linked.get(pid, [])))})
    return out


# ---------------------------------------------------------------- check + report
def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="write no report; exit 1 on any problem")
    args = ap.parse_args()

    cfg = load_config(ROOT)
    base = base_dir(reference_root(GAME), str(cfg.megapack["base_game"]["version"]))
    decided = yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}
    keep, keep_alike = decided.get("keep") or {}, decided.get("lookalikes") or {}
    units = read_units(sorted((base / "def").glob("achievements*.sii")))
    if not units:
        raise SystemExit(f"no achievement units in {base / 'def'} — extract base_cfg.scs (extract-reference --deep)")
    achs = achievements(units)
    checked = slots(achs)
    links = pack_links(cfg, set(checked))
    names, pack_cargo = cargo_names(cfg, base)
    vanilla = {key: {p.name.removesuffix(".sii") for p in (base / "def" / "company" / key[0] / key[1]).glob("*.sii")}
               for key in checked}

    problems = []
    for key in sorted(set(keep) - {f"{c}/{d}" for c, d in checked}):
        problems.append(f"cargo/achievements.yaml keeps links at {key}, which no achievement checks")
    for key, ls in sorted(links.items()):
        slot = f"{key[0]}/{key[1]}"
        kept = set((keep.get(slot) or {}).get("links") or [])
        if kept and not (keep[slot] or {}).get("reason"):
            problems.append(f"cargo/achievements.yaml `keep` {slot} has no reason")
        shipped = {x["name"] for x in ls if not x["exclude"]}
        for x in ls:
            x["decision"] = (f"dropped (`{x['exclude']}`)" if x["exclude"] else "kept" if x["name"] in kept
                             else "UNDECIDED")
            if x["decision"] == "UNDECIDED":
                ids = ", ".join(e["id"] for e in checked[key])
                problems.append(f"{x['path']} ({x['source']}, cargo {x['cargo'] or '(blank)'}) is at {slot}, which "
                                f"{ids} checks: exclude it in megapack.yaml or keep it in cargo/achievements.yaml")
        for name in sorted(kept - shipped):
            problems.append(f"cargo/achievements.yaml keeps {slot} {name}, which the pack does not ship there")
    for key in sorted(set(keep) - {f"{c}/{d}" for c, d in links}):
        if key in {f"{c}/{d}" for c, d in checked}:
            problems.append(f"cargo/achievements.yaml keeps links at {key}, where the pack ships none")
    named = {c for a in achs for r in a["reqs"] for c in r["cargos"]}
    for cid in sorted(named & set(pack_cargo)):
        problems.append(f"{pack_cargo[cid]} replaces cargo {cid}, which an achievement names: exclude it")
    alike = lookalikes(cfg, achs, names, pack_cargo)
    for x in alike:
        if x["links"] and x["pack"] not in keep_alike:
            problems.append(f"pack cargo {x['pack']} is named like {x['cargo']} ({names[x['cargo']]}), which {x['id']} "
                            f"counts, and {len(x['links'])} link(s) offer it: exclude them or list it under "
                            "`lookalikes` in cargo/achievements.yaml")
    for pid in sorted(set(keep_alike) - {x["pack"] for x in alike if x["links"]}):
        problems.append(f"cargo/achievements.yaml `lookalikes` lists {pid}, which no achievement's cargo shares a name "
                        "with any more, or nothing offers")

    if not args.check:
        write_report(achs, checked, links, vanilla, names, keep, alike, keep_alike)
    for p in problems:
        print(f"problem: {p}", file=sys.stderr)
    count = lambda d: sum(1 for v in links.values() for x in v if x["decision"].startswith(d))
    print(f"{len(achs)} achievements filter by cargo, {len(checked)} company slots checked; pack links there: "
          f"{count('dropped')} dropped, {count('kept')} kept, {count('UNDECIDED')} undecided; {len(problems)} problem(s)"
          + ("" if args.check else f"; report {REPORT.relative_to(ROOT)}"))
    sys.exit(1 if problems else 0)


def write_report(achs, checked, links, vanilla, names, keep, alike, keep_alike):
    name = lambda cid: f"{cid} ({names[cid]})" if cid in names else cid
    lines = ["# Achievement company slots", "",
             "Generated by `python tools/achievement_guard.py` from the base game's `def/achievements*.sii`,",
             "`megapack.yaml` `exclude` and `cargo/achievements.yaml` `keep`",
             "([ADR-0003](../docs/adr/ADR-0003-achievement-company-slots-stay-vanilla.md)). A link applies to the",
             "company in every city, so a drop removes the cargo there everywhere.", ""]
    for key in sorted(checked):
        slot = f"{key[0]}/{key[1]}"
        lines += [f"## {slot}", ""]
        for e in checked[key]:
            lines.append(f"- **{e['id']}** ({e['file']}), {', '.join(sorted(e['places']))}: "
                         + ", ".join(name(c) for c in sorted(e["cargos"])))
        lines.append(f"- vanilla links: {', '.join(sorted(vanilla[key])) or 'none'}")
        reason = (keep.get(slot) or {}).get("reason")
        if reason:
            lines.append(f"- kept because: {reason}")
        ls = links.get(key, [])
        if not ls:
            lines += ["- pack links: none", ""]
            continue
        lines += ["", "| Link | Source | Cargo | Replaces vanilla | Decision |", "|---|---|---|---|---|"]
        for x in ls:
            lines.append(f"| {x['name']} | {x['source']} | {name(x['cargo']) if x['cargo'] else '(blank)'} | "
                         f"{'yes' if x['name'] in vanilla[key] else ''} | {x['decision']} |")
        lines.append("")
    company_less = [a for a in achs if not any(r["companies"] for r in a["reqs"])]
    lines += ["## Cargo filters without a company", "",
              "These count a cargo wherever it is loaded or delivered (some within a list of countries). `--check`",
              "fails on a pack cargo definition with the same id, or on a pack cargo with the same name that a merged",
              "link offers, unless `lookalikes` in `cargo/achievements.yaml` keeps it.", ""]
    for a in company_less:
        cargos = sorted({c for r in a["reqs"] for c in r["cargos"]})
        places = sorted({p for r in a["reqs"] for p in r["places"]})
        lines.append(f"- **{a['id']}** ({a['file']}){', ' + ', '.join(places) if places else ''}: "
                     + ", ".join(name(c) for c in cargos))
    lines += ["", "Pack cargoes with the same name as one of these:", ""]
    for x in alike:
        where = ", ".join(x["links"]) if x["links"] else "no merged link offers it"
        kept = f"; kept: {keep_alike[x['pack']]}" if x["pack"] in keep_alike else ""
        lines.append(f"- {x['pack']}, named like {name(x['cargo'])} ({x['id']}): {where}{kept}")
    if not alike:
        lines.append("- none")
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
