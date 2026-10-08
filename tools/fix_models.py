#!/usr/bin/env python3
"""Fix misnamed locators in Jazzycat models, written into overrides/.

Jazzycat's main-pack flatbed4 names its body locator `hook` (a second one, at the origin), so the game logs
"Unable to find body locator for trailer body in chassis /vehicle/t_jazzycat/flatbed4/flatbed4.pmd" and has
nowhere to put the flatbed4j cargo bodies. Military's copy of the same model (same geometry) names it `body`.
This tool renames only that locator's name token in the source model; every other byte stays the same:

    python tools/fix_models.py           -> overrides/<path> for every entry in FIXES
    python tools/fix_models.py --check   -> exit 1 if an override is missing or differs from what it would write

Each override replaces a file a source ships, so resolutions.yaml stamps the source copy it was made from and
`megapack check` warns when Jazzycat changes it upstream: then rerun this tool and update the entry's `inputs`.
"""
import argparse
import sys
from pathlib import Path

import yaml

from cargo_rebalance import GAME, ROOT, reference_root

sys.path.insert(0, str(Path.home() / ".agent-brains" / "profiles" / "scs-mod-developer" / "skills" / "megapack" / "scripts"))
from pmg import LOCATOR, Pmg, token_value  # noqa: E402

# (source id, model path, (locator name, hookup, n-th such locator), new name)
FIXES = [
    ("jazzycat-trailers-cargo", "vehicle/t_jazzycat/flatbed4/flatbed4.pmg", ("hook", "", 1), "body"),
]


def rename_locator(src: Pmg, key: tuple[str, str, int], new: str) -> bytes:
    keys = src.locator_keys()
    if key not in keys:
        raise SystemExit(f"{src.label}: no locator {key} (fixed upstream? remove it from FIXES)")
    if any(k[0] == new for k in keys):
        raise SystemExit(f"{src.label}: already has a `{new}` locator (fixed upstream? remove it from FIXES)")
    i = keys.index(key)
    off = src.locators_off + LOCATOR.size * i
    data = bytearray(src.data)
    data[off:off + 8] = token_value(new).to_bytes(8, "little")
    out = Pmg(bytes(data), src.label)
    before = [(l.name, l.hookup, l.position, l.rotation) for l in src.locators]
    after = [(l.name, l.hookup, l.position, l.rotation) for l in out.locators]
    changed = [j for j, (a, b) in enumerate(zip(before, after)) if a != b]
    if changed != [i] or after[i][0] != new or out.geometry_fingerprint() != src.geometry_fingerprint():
        raise SystemExit(f"{src.label}: rename touched more than locator {i}")
    return bytes(data)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--check", action="store_true", help="verify the overrides instead of writing them")
    args = ap.parse_args()

    ref_root = reference_root(GAME)
    versions = {s["id"]: str(s["version"])
                for s in yaml.safe_load((ROOT / "sources.yaml").read_text(encoding="utf-8"))["sources"]}
    bad = 0
    for sid, rel, key, new in FIXES:
        src_path = ref_root / "local" / sid / versions[sid] / rel
        if not src_path.is_file():
            raise SystemExit(f"{src_path} missing: extract {sid} {versions[sid]} (extract-reference)")
        want = rename_locator(Pmg.read(src_path), key, new)
        out = ROOT / "overrides" / rel
        same = out.is_file() and out.read_bytes() == want
        if args.check:
            bad += not same
            print(f"{'ok' if same else 'STALE'}  overrides/{rel}")
        else:
            if not same:
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(want)
            print(f"{'unchanged' if same else 'wrote'}  overrides/{rel}  ({key[0]}#{key[2]} -> {new})")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
