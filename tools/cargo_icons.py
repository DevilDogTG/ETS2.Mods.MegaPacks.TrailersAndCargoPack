#!/usr/bin/env python3
"""Freight-market icons for the merged Jazzycat cargo.

The game looks a cargo's icon up only by name, at /material/ui/cargo_icons/<cargo_id>.mat, and Jazzycat ships none
(one "Missing default icon for cargo" warning per cargo, blank icon in the freight market). This tool picks a
base-game icon for every merged cargo using cargo/icons.yaml and writes an alias .mat for it, the way vanilla aliases
its own variants (apples_c.mat -> apples.tobj):

    python tools/cargo_icons.py   -> overrides/material/ui/cargo_icons/<id>.mat, cargo/icons.md

Only base-game icons are used (cargoes @included by vanilla def/cargo.sii): a DLC texture is missing for a player
who does not own that DLC. The output folder belongs to this tool; files it did not write this run are removed.

It also fills the base game's own gaps: a base cargo vanilla ships without a .mat (ETS2 1.62: battery, chem_granule,
chlorine_t, sulfuric_t) gets one, to the icon `vanilla:` in icons.yaml names or else to its own .tobj.
"""
import re
from collections import Counter
from pathlib import Path

import yaml

from cargo_rebalance import CARGO_RE, GAME, LIST_RE, ROOT, base_dir, reference_root, sources_in_layer_order

CONFIG = ROOT / "cargo" / "icons.yaml"
OUT_DIR = ROOT / "overrides" / "material" / "ui" / "cargo_icons"
REPORT = ROOT / "cargo" / "icons.md"
ICON_DIR = "material/ui/cargo_icons"
SUFFIX_RE = re.compile(r"(_?j(r|p|e|cy|tz|ptz)?\d*r?|_?\d+|_)$")  # Jazzycat variant suffixes: _j1, j, jr2, _jp1, j1r, 01
PREFIXES = ("c_", "s_", "r_")                                     # container / schmitz / reefer variants


def base_cargo(base: Path) -> list[str]:
    """Base-game cargo ids: the ones vanilla def/cargo.sii includes (not DLC)."""
    text = (base / "def" / "cargo.sii").read_text(encoding="utf-8-sig")
    return re.findall(r'@include\s+"cargo/([^"]+)\.sui"', text)


def base_icons(base: Path) -> dict[str, str]:
    """Base-game cargo id -> its .mat text, for base-game cargoes that have one."""
    out = {}
    for cid in base_cargo(base):
        mat = base / ICON_DIR / f"{cid}.mat"
        if mat.is_file():
            out[cid] = mat.read_text(encoding="utf-8-sig")
    return out


def vanilla_gaps(base: Path, cfg: dict, icons: dict) -> dict[str, tuple[str, str]]:
    """Base-game cargo id -> (.mat text, icon) for the base cargoes vanilla ships without a .mat."""
    out, unmapped = {}, []
    for cid in base_cargo(base):
        if cid in icons:
            continue
        if cid in cfg["vanilla"]:
            icon = cfg["vanilla"][cid]
            out[cid] = (alias_mat(icons[icon]), icon)
        elif (base / ICON_DIR / f"{cid}.tobj").is_file():  # texture without a material: a vanilla .mat pointed at it
            mat = re.sub(r'(source\s*:\s*")[^"]*"', rf'\g<1>{cid}.tobj"', icons[cfg["default"]])
            out[cid] = (alias_mat(mat), f"{cid}.tobj")
        else:
            unmapped.append(cid)
    if unmapped:
        raise SystemExit(f"base cargo without an icon; map it under `vanilla` in cargo/icons.yaml: {', '.join(unmapped)}")
    stale = sorted(set(cfg["vanilla"]) - set(out))
    if stale:
        raise SystemExit(f"cargo/icons.yaml `vanilla` names cargo that is not a base-game icon gap: {', '.join(stale)}")
    return out


def merged_cargo(ref_root: Path) -> dict[str, dict]:
    """cargo id -> source and groups, later layer wins (as the build resolves it)."""
    out = {}
    for sid, root in sources_in_layer_order(ref_root):
        for p in (root / "def" / "cargo").glob("*.sui"):
            text = p.read_text(encoding="utf-8-sig")
            m = CARGO_RE.search(text)
            if m:  # SII tokens are case-insensitive; the game looks the icon up lower-case (beer_can_J1)
                out[m.group(1).lower()] = {"source": sid, "groups": LIST_RE["group"].findall(text)}
    return out


def stems(cid: str):
    for name in [cid] + [cid[len(p):] for p in PREFIXES if cid.startswith(p)]:
        prev = None
        while name and name != prev:
            prev, name = name, SUFFIX_RE.sub("", name)
            yield name


def pick(cid: str, info: dict, cfg: dict, icons: dict) -> tuple[str, str]:
    if cid in cfg["exact"]:
        return cfg["exact"][cid], "exact"
    for pattern, icon in cfg["rules"]:
        if re.search(pattern, cid):
            return icon, f"rule `{pattern}`"
    for s in stems(cid):
        for cand in (s, s + "s", s + "es", s.rstrip("s")):
            if cand in icons:
                return cand, "name"
    if info["source"] in cfg["source"]:
        return cfg["source"][info["source"]], "source"
    for group, icon in cfg["groups"]:
        if group in info["groups"]:
            return icon, f"group {group}"
    return cfg["default"], "default"


def alias_mat(target_mat: str) -> str:
    """The target's material with its texture source made absolute, so it resolves from another file name."""
    return re.sub(r'(source\s*:\s*")([^"/][^"]*)"', rf'\1/{ICON_DIR}/\2"', target_mat)


def main():
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    mp = yaml.safe_load((ROOT / "megapack.yaml").read_text(encoding="utf-8"))
    ref_root = reference_root(GAME)
    base = base_dir(ref_root, str(mp["base_game"]["version"]))
    icons = base_icons(base)

    named = list(cfg["exact"].values()) + [i for _, i in cfg["rules"]] + list(cfg["source"].values())
    named += [i for _, i in cfg["groups"]] + [cfg["default"]] + list(cfg["vanilla"].values())
    unknown = sorted({i for i in named if i not in icons})
    if unknown:
        raise SystemExit(f"cargo/icons.yaml names icons that are not base-game cargo icons: {', '.join(unknown)}")
    gaps = vanilla_gaps(base, cfg, icons)

    cargo = merged_cargo(ref_root)
    stale_exact = sorted(set(cfg["exact"]) - set(cargo))
    if stale_exact:
        raise SystemExit(f"cargo/icons.yaml `exact` names cargo no source ships: {', '.join(stale_exact)}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    written = set()

    def write(cid: str, content: str):
        path = OUT_DIR / f"{cid}.mat"
        if not path.is_file() or path.read_text(encoding="utf-8") != content:
            path.write_text(content, encoding="utf-8", newline="\n")
        written.add(path.name)

    for cid, (content, _) in sorted(gaps.items()):
        write(cid, content)
    rows = []
    for cid, info in sorted(cargo.items()):
        if cid in icons or cid in gaps:
            continue  # a Jazzycat cargo reusing a vanilla id already has (or gets) the vanilla icon
        icon, how = pick(cid, info, cfg, icons)
        write(cid, alias_mat(icons[icon]))
        rows.append((cid, info["source"], ",".join(info["groups"]), icon, how))
    removed = [p for p in OUT_DIR.glob("*.mat") if p.name not in written]
    for p in removed:
        p.unlink()

    by_how = Counter(r[4].split(" ")[0] for r in rows)
    lines = ["# Cargo icons", "", "Generated by `python tools/cargo_icons.py` from `cargo/icons.yaml`: one alias `.mat` per",
             f"Jazzycat cargo in `overrides/{ICON_DIR}/`, pointing at a base-game icon.", "",
             f"{len(rows)} cargoes: " + ", ".join(f"{n} by {k}" for k, n in by_how.most_common()) + ".", "",
             f"Base-game cargoes the base game ships without an icon `.mat` ({len(gaps)}):", "",
             "| Cargo | Icon |", "|---|---|"]
    lines += [f"| {c} | {i} |" for c, (_, i) in sorted(gaps.items())]
    lines += ["", "| Cargo | Source | Groups | Icon | Picked by |", "|---|---|---|---|---|"]
    lines += [f"| {c} | {s} | {g} | {i} | {h} |" for c, s, g, i, h in rows]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"{len(rows)} icons in {OUT_DIR.relative_to(ROOT)} ({', '.join(f'{k} {n}' for k, n in by_how.most_common())}); "
          f"{len(gaps)} base-game gaps; {len(removed)} stale removed; report {REPORT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
