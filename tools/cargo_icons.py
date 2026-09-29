#!/usr/bin/env python3
"""Freight-market icons for the merged Jazzycat cargo.

The game looks a cargo's icon up only by name, at /material/ui/cargo_icons/<cargo_id>.mat, and Jazzycat ships none
(one "Missing default icon for cargo" warning per cargo, blank icon in the freight market). This tool picks a
base-game icon for every merged cargo using cargo/icons.yaml and writes an alias .mat for it, the way vanilla aliases
its own variants (apples_c.mat -> apples.tobj):

    python tools/cargo_icons.py   -> overrides/material/ui/cargo_icons/<id>.mat, cargo/icons.md

Only base-game icons are used (cargoes @included by vanilla def/cargo.sii): a DLC texture is missing for a player
who does not own that DLC. The output folder belongs to this tool; files it did not write this run are removed.
"""
import re
from collections import Counter
from pathlib import Path

import yaml

from cargo_rebalance import CARGO_RE, LIST_RE, ROOT, host_section, sources_in_layer_order

CONFIG = ROOT / "cargo" / "icons.yaml"
OUT_DIR = ROOT / "overrides" / "material" / "ui" / "cargo_icons"
REPORT = ROOT / "cargo" / "icons.md"
ICON_DIR = "material/ui/cargo_icons"
SUFFIX_RE = re.compile(r"(_?j(r|p|e|cy|tz|ptz)?\d*r?|_?\d+|_)$")  # Jazzycat variant suffixes: _j1, j, jr2, _jp1, j1r, 01
PREFIXES = ("c_", "s_", "r_")                                     # container / schmitz / reefer variants


def base_icons(base: Path) -> dict[str, str]:
    """Base-game cargo id -> its .mat text, for cargoes vanilla def/cargo.sii includes (not DLC)."""
    text = (base / "def" / "cargo.sii").read_text(encoding="utf-8-sig")
    out = {}
    for cid in re.findall(r'@include\s+"cargo/([^"]+)\.sui"', text):
        mat = base / ICON_DIR / f"{cid}.mat"
        if mat.is_file():
            out[cid] = mat.read_text(encoding="utf-8-sig")
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
    ref_root = Path(host_section("Extracted Reference Root")["root"])
    icons = base_icons(ref_root / "base" / str(mp["base_game"]["version"]) )

    named = list(cfg["exact"].values()) + [i for _, i in cfg["rules"]] + list(cfg["source"].values())
    named += [i for _, i in cfg["groups"]] + [cfg["default"]]
    unknown = sorted({i for i in named if i not in icons})
    if unknown:
        raise SystemExit(f"cargo/icons.yaml names icons that are not base-game cargo icons: {', '.join(unknown)}")

    cargo = merged_cargo(ref_root)
    stale_exact = sorted(set(cfg["exact"]) - set(cargo))
    if stale_exact:
        raise SystemExit(f"cargo/icons.yaml `exact` names cargo no source ships: {', '.join(stale_exact)}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows, written = [], set()
    for cid, info in sorted(cargo.items()):
        if cid in icons:
            continue  # a Jazzycat cargo reusing a vanilla id already has the vanilla icon
        icon, how = pick(cid, info, cfg, icons)
        path = OUT_DIR / f"{cid}.mat"
        content = alias_mat(icons[icon])
        if not path.is_file() or path.read_text(encoding="utf-8") != content:
            path.write_text(content, encoding="utf-8", newline="\n")
        written.add(path.name)
        rows.append((cid, info["source"], ",".join(info["groups"]), icon, how))
    removed = [p for p in OUT_DIR.glob("*.mat") if p.name not in written]
    for p in removed:
        p.unlink()

    by_how = Counter(r[4].split(" ")[0] for r in rows)
    lines = ["# Cargo icons", "", "Generated by `python tools/cargo_icons.py` from `cargo/icons.yaml`: one alias `.mat` per",
             f"Jazzycat cargo in `overrides/{ICON_DIR}/`, pointing at a base-game icon.", "",
             f"{len(rows)} cargoes: " + ", ".join(f"{n} by {k}" for k, n in by_how.most_common()) + ".", "",
             "| Cargo | Source | Groups | Icon | Picked by |", "|---|---|---|---|---|"]
    lines += [f"| {c} | {s} | {g} | {i} | {h} |" for c, s, g, i, h in rows]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"{len(rows)} icons in {OUT_DIR.relative_to(ROOT)} ({', '.join(f'{k} {n}' for k, n in by_how.most_common())}); "
          f"{len(removed)} stale removed; report {REPORT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
