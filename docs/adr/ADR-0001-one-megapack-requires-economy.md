# ADR-0001: One megapack for Jazzycat trailers and cargo, requiring DriveDogs Economy

**Date:** 2026-09-28
**Status:** accepted
**Deciders:** DevilDogTG

## Context
Jazzycat publishes trailers and cargo together: each pack ships company trailers, cargo jobs, AI traffic
trailers and their models in the same archives. A scan of the current packs (main Trailers & cargo 11.10.6,
Overweight 11.10.5, Military 6.8.7, Railway 4.6.7) found:

- Each cargo has its own `trailer_def` (`def/cargo/<id>/<trailer>.sii`) that names a Jazzycat trailer unit
  (1,587 references) and sets the trailer's capacity. Job pay per load = `unit_reward_per_km` x units, and the
  units come from that capacity, so cargo and trailer defs together decide pay. The trailer model has no
  economy data.
- The trailers are not ownable (no dealer or owned-trailer defs). They appear only through cargo jobs and AI
  traffic, so trailers without cargo add nothing to the game.
- The Overweight pack is a strict subset of the main pack: all 381 of its cargoes are in the main pack, and
  where files differ the main pack is newer. Both ship `def/cargo.jazzycat.sii`, so loading both lets the
  older list override the newer.
- The main pack registers 724 AI traffic trailers itself (`traffic_storage_trailer_semi.jazzycat_tr.sii`);
  Military ships its traffic registration as a separate add-on archive.
- Jazzycat pays nearly every cargo the same (about 20-22 EUR/km per load against a vanilla median of 19.9),
  with no difference for weight, hazard or value. The maintainer wants cargo pay to follow DriveDogs
  Economy's rules, and Economy stays a standalone mod.

## Options Considered

### Option A: One megapack with trailers, cargo, traffic and the pay rebalance
- **Pros:** one mod, requiring only DriveDogs Economy; sources are locked once, so trailers and cargo can
  never be built from different Jazzycat versions; no rules needed to split files between repos.
- **Cons:** every build repacks all parts (about 9 GB of assets), including releases that only change pay.

### Option B: Two megapacks split by trailers vs cargo
- **Pros:** a pay-only release repacks only the cargo pack (cargo defs + cargo models, ~2.4 GB).
- **Cons:** the cargo pack needs the trailer pack (its trailer_defs point at the trailer units) and the
  trailer pack does nothing alone; both repos must lock the same Jazzycat version, or cargo jobs reference
  trailers that do not exist; complementary excludes must cover every source file exactly once.

### Option C: Two megapacks split by assets vs economy defs
- **Pros:** a pay-only release repacks only a few MB of defs.
- **Cons:** the same version-skew and coverage problems as B, and still two mods that only work together.

## Decision
Option A. Sources: main Trailers & cargo pack, Military (English cargo names), Military traffic add-on and
Railway. AI traffic trailers stay in. The Overweight pack is dropped as a duplicate of the main pack. The pack
requires DriveDogs Economy, and its cargo pay rebalance reads Economy's rules from the Economy repo
(recorded in a later ADR). Archive names carry the version (`_v<version>`) and every part carries the pack
version, as in the AI Traffic megapack.

## Consequences
**Easier:** one lock and one collision model for all Jazzycat trailer and cargo content; one entry in the
load order next to Economy.
**Harder:** each release, including pay-only ones, repacks every part. A skill change to reuse unchanged
parts was considered and deferred, because every part shows the pack version and would need repacking on
each version bump anyway; revisit if build time becomes a problem.
**Update 2026-09-28:** the pack has no separate def part (`split_defs: false`), since every build repacks all
parts anyway, and it drops cargo links to companies the base game lacks (`exclude_unknown_companies`; 67k of
140k link files, for map mods the maintainer does not run). Result: 3 archives instead of 5.
**Update 2026-10-01:** a 5.09 GiB archive loads in game (DriveDogs World), so `max_part_bytes` is 5 GiB: 2 archives
from 1.0.2, split by the forum's 60,000-entries-per-archive limit. That limit looks wrong for HashFS mods (AiTrafficPack
loaded one archive of 86,583 entries), so 1.1.0-dev.2 tests the pack as one archive. Company cargo-link files cannot be
merged to save entries: the game reads each as exactly one unit (1.1.0-dev.1 broke cargo).
**Follow-up:** check paths this pack shares with the AI Traffic megapack (both carry Jazzycat content) and
set the load order from that.
