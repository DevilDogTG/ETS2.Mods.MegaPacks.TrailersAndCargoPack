# ADR-0003: Company slots that achievements check stay vanilla

**Date:** 2026-11-08
**Status:** accepted
**Deciders:** DevilDogTG

## Context
The maintainer's Gas must flow and Volvo Trucks Lover deliveries did not count (ETS2 1.62.1.0, pack 1.1.2). Some
achievements count only a vanilla cargo delivered from or to one company. This pack linked Jazzycat cargo to exactly
those companies:

| Achievement | Counts | Pack links there (1.1.2) |
|---|---|---|
| Gas must flow (`fr_truckstop`) | vanilla fuels to BP (`eco/in`) in 7 French cities | 8 fuel look-alikes ("Diesel", "Gasoline", "LPG") |
| Volvo Trucks Lover (`sc_volvo_cargo`) | Volvo Trucks from the Volvo factory, Göteborg (`volvo_fac/out`) | 9, incl. "Volvo Trucks", "Volvo FMX" |
| Scania Trucks Lover (`sc_scania_cargo`) | Scania Trucks from the Scania factory, Södertälje (`scania_fac/out`) | 10, incl. "Scania Trucks" |
| Temple Worthy (`gr_marble`) | marble from Greek quarries (`rock_eater/out`) | 48, incl. 2 "Marble Blocks" |
| Gift of Athena (`gr_olive`) | olives and olive oil from Greek olive farms (`eliarchos/out`) | 25 fruit, vegetables, grain |
| Cattle Drive (`sc_cows_to_farm`) | live cattle to farms and København airport (`freyr/in`, `fle/in`) | 53 airport cargoes (none at `freyr`) |

A look-alike shows the same name and icon in the job list and delivery log but does not count, and every extra cargo
at a company makes the vanilla job rarer. Two more things showed up:
- At both truck factories Jazzycat ships its own copies of vanilla `empty_palet.dlc_north.sii` and
  `used_packag.dlc_north.sii` with `cargo: ""`, which switch those vanilla jobs off.
- A few achievements count a cargo with no company (Heavy Cargo, Special Transport, the West Balkans production
  chain). Jazzycat's three "Transformer" cargoes share the name of the Heavy Cargo Pack's `transformat`, and they are
  offered all over the map.

A cargo link file holds only `cargo:`, no city, so it applies to the company in every city. The 1.62 map
(`map/europe/*.base`) shows this barely matters: `eco` exists only in the 7 Gas must flow cities, `volvo_fac` only in
Göteborg, `scania_fac` only in Södertälje; only `rock_eater` (17 cities, 4 in Greece) loses pack cargo outside the
achievement's cities.

## Options Considered

### Option A: Drop the look-alikes everywhere they appear
- **Pros:** no confusion anywhere.
- **Cons:** removes common cargo (Jazzycat diesel, marble) from companies no achievement checks.

### Option B: Rename every look-alike
- **Pros:** no cargo lost.
- **Cons:** a cargo's name is global, so it changes everywhere; the vanilla job at the slot stays rarer; does not help
  with a different-name cargo that misleads by context ("Volvo FMX" from the Volvo factory); a literal name loses the
  translations.

### Option C: Drop at the slot when the achievement names a company, rename when it does not
- **Pros:** the drop is local to the company the achievement checks and keeps its job odds vanilla; the rename is
  used only where a drop would be map-wide.
- **Cons:** a drop at a company applies to all its cities (only the marble, in 13 non-Greek quarries).

## Decision
Option C (maintainer, 2026-11-08):
- `megapack.yaml` `exclude`: everything the pack adds at `eco/in`, `volvo_fac/out` and `scania_fac/out` (vanilla
  Empty Pallets and Used Packaging come back), and the marble look-alikes `mram_bl_j*` at `rock_eater/out`.
- `cargo/achievements.yaml` `keep`: the other pack links at checked slots that cannot be mistaken for the counted
  cargo (quarry machinery, olive-farm produce, airport cargo), each slot with its reason.
- `cargo/fixes.yaml`: the three Jazzycat Transformers are renamed "Transformer (Jazzycat)" (English in every language).
- `tools/achievement_guard.py` reads the base game's `def/achievements*.sii` on every build and fails `--check` on any
  pack link at a checked slot that is neither excluded nor kept, a stale `keep` entry, a pack cargo replacing one an
  achievement names, or a same-name pack cargo for a company-less achievement that a merged link offers. A new case
  after a Jazzycat or game update stops the build until the maintainer decides it.

## Consequences
- Rerun the guard after every source or game update; new achievements or new links appear as problems, not silently.
- Deliveries made with a look-alike before the fix never count retroactively.
- The Jazzycat Transformers show an English name in every game language.
