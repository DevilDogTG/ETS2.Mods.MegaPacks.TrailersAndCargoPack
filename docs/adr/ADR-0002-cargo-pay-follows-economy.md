# ADR-0002: Jazzycat cargo pay follows DriveDogs Economy

**Date:** 2026-09-28
**Status:** accepted
**Deciders:** DevilDogTG

## Context
This pack requires DriveDogs Economy (ADR-0001). Economy balances cargo pay per trailer load, not per unit (its
ADR-0001): a job pays `unit_reward_per_km` x units, units come from the cargo's trailer_defs, and categories are
set as multiples of vanilla's median load (Economy's anchor, 19.87 EUR/km for 1.61.1.1). Economy raises hazmat
by ADR class (1: 1.5x, 6: 1.4x, 8: 1.35x, 2: 1.3x, 4: 1.2x), keeps categories vanilla already pays a premium
(ADR class 3), caps any cargo at 2x and never lowers a vanilla rate. Its principle: every pay difference needs a
reason sized to it.

Measured the same way (`tools/cargo_rebalance.py analyze`, `cargo/analysis.md`), Jazzycat pays nearly every
cargo the same, 20-22 EUR/km per load. Against vanilla for the same kind of cargo:

| kind | Jazzycat | vanilla | with Economy |
|---|---|---|---|
| ordinary, valuable, fragile | 1.01-1.11x | 0.97-1.12x | same |
| overweight (257) | 1.11x | 1.46x | 1.46x |
| ADR class 1 / 2 / 3 / 4 / 8 | 1.01-1.11x | 1.06-1.60x | 1.5 / 1.3 / 1.6 / 1.2 / 1.35x |
| bulk group (22) | 1.01x | 0.54x | 0.54x |

The data also has bugs: trailer limits that fit a fraction of the load (`forklift1j` 420 kg payload, 1 EUR/km),
a decimal slip (`banan_j2` 2,027 kg per unit), a body type pointing at another cargo's trailer (`flowers_j1`).

## Options Considered

### Option A: Leave Jazzycat's pay
- **Pros:** nothing to maintain.
- **Cons:** heavy haulage and hazmat pay like an ordinary job while the same kind of vanilla cargo pays up to
  1.6x under Economy; bulk pays twice vanilla bulk; broken jobs stay broken.

### Option B: Copy Economy's numbers into this repo
- **Pros:** no dependency on the Economy checkout at build time.
- **Cons:** the numbers drift silently when Economy changes a rule.

### Option C: Generate rates from Economy's own code, per load, on fixed data
`tools/cargo_rebalance.py generate` imports Economy's rules and units maths from the Economy repo (host root
`@drivedogs_economy`), applies the hand-reviewed fixes in `cargo/fixes.yaml`, and moves each group's median
pay per load to its target. It writes `cargo/edits.yaml`, which the megapack applies at build (`base_edits`).
- **Pros:** one source of truth for the rules; targets read as "N x an ordinary job"; every change carries a
  comment with its rule and before/after pay.
- **Cons:** generating needs the Economy checkout; rerun after any Economy rule change.

## Decision
Option C, with these targets (median pay per load, as a multiple of Economy's anchor):
- **ADR:** Economy's hazmat tier for the class; a class Economy leaves alone (3) gets vanilla's own premium for
  that class (1.60x). All 47 Jazzycat ADR cargoes set `adr_class`.
- **Overweight:** vanilla overweight cargo's median, 1.46x (heavy and oversize haulage).
- **Bulk (group):** vanilla bulk's median, 0.54x. The only group whose pay goes down: Jazzycat paid it twice
  vanilla bulk with no reason (maintainer's call).
- Ordinary, valuable and fragile cargo keep Jazzycat's pay (already at vanilla's level).
- Premiums don't stack: a cargo in several groups takes the highest target. Economy's 2x cap applies; a premium
  never lowers a cargo's rate.
- Each group is scaled as a whole (Economy's method), so differences inside a group stay.
- **Data fixes** keep the cargo's real weight and fix the wrong number: a decimal slip in mass, a mismatched
  body type, and trailer limits raised only to fit the cargo's full load on that cargo's own trailer_def, where
  the same trailer carries at least that load in another Jazzycat cargo (or on the maintainer's call: `edk300`).
- Cargo that is never offered (disabled by Jazzycat, map-mod companies only, capital-letter IDs) stays as shipped.

The units maths skips trailer_defs that cannot take one unit (the game never assigns them). Economy counts them
as zero units, which zeroes 30 vanilla heavy cargoes; the anchor still comes from Economy's own code so the
targets stay aligned with Economy.

## Consequences
**Easier:** a rule change in Economy reaches this pack by rerunning `generate` and rebuilding; each rate in
`cargo/edits.yaml` explains itself.
**Harder:** the Economy checkout must be present to generate; a Jazzycat update needs `analyze` and `generate`
again, and `megapack check` fails if a fixed or rebalanced unit disappears.
**Follow-up:** playtest pay (in-game offers should be about 2x the per-load EUR/km, Economy's calibration);
the Economy units-maths gap is reported to the maintainer, Economy itself is unchanged.
