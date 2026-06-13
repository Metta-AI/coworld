# METADATA

- topic: CrewRift player optimizer learnings
- date: 2026-06-13
- iso_week: 202624
- author_handle: Richard Higgins / RelhAlpha
- author_player_ids:
  - Richard Higgins: `ply_ded11f40-3e30-4921-b019-f7f6bc3e9c83`
  - RelhAlpha: `ply_18302115-9fc9-482d-a2f3-f4c592bf9e57`
- source_machines:
  - `zephyrus`: co-gas CrewRift Suspectra remote-XP loop through v108.
  - `xpser`: co-gas CrewRift remote-XP package with source-custody and candidate-ledger lessons.
  - `mbp`: RelhAlpha/player-labs CrewRift `crewborg` onboarding and first hosted evaluation loop.
  - `titan`: replay-driven Coworld policy-debugging package; no direct CrewRift
    optimizer findings were retained.
- tiers:
  - `crewrift-specific`
  - `remote-xp-optimizer-loop`
  - `generic`
- roots_swept_across_machines:
  - `/home/relh/Code/co-gas`
  - `/home/relh/Code/fourth/co-gas`
  - `/Users/relh/packages/crewrift-player-optimizer`
  - `/home/relh/Code/metta`
  - `/tmp/coworld-crewrift-source`
  - local Codex and Claude session directories on each machine
This package integrates four machine-specific extractions into one canonical
CrewRift player optimizer package. Direct CrewRift findings came from zephyrus,
xpser, and mbp. Titan was reviewed as part of the merge, but its unrelated
machine-history material was cut rather than carried into the active package.
Machine-specific directories were collapsed after integration; per-machine
provenance lives in `source-machines/INDEX.md`.
