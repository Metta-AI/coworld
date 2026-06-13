# Source Machine Provenance

The integrated package reviewed four machine-specific submissions. Direct
CrewRift optimizer findings came from zephyrus, xpser, and mbp. Titan did not
contain direct CrewRift optimization findings, so its unrelated details were cut
and only the process gap is recorded.

## zephyrus

- Original path: `packages/coworld/templates/optimizers/202624/richard-higgins-zephyrus`
- Main contribution: co-gas Suspectra v98-v108 remote XP loop, the v108 no-XP
  caveat, and session-mined candidate state discipline.
- Integrated into: top-level `LOOP.md`, `performance/LOG.md`,
  `crewrift-specific/`, and `remote-xp-optimizer-loop/`.

## xpser

- Original path: `packages/coworld/templates/optimizers/242026/xpser-co-gas-crewrift-player-optimizer`
- Main contribution: co-gas remote-XP state machine, candidate ledger lessons,
  source custody, and concrete failure classes from Suspectra work.
- Integrated into: `remote-xp-optimizer-loop/`, `universal/`, and
  `crewrift-specific/`.

## mbp

- Original path: `packages/coworld/templates/optimizers/242026/relhalpha-mbp-phase1-review`
- Main contribution: RelhAlpha/player-labs onboarding loop, active policy
  recording, current roster construction, full artifact fetch, player identity
  submission, and side-by-side lane reporting.
- Integrated into: top-level `LOOP.md`, `performance/LOG.md`, and
  `crewrift-specific/guides/crewrift-policy-notes.md`.

## titan

- Original path: `packages/coworld/templates/optimizers/242026/titan`
- Main finding: no direct prior CrewRift optimizer sessions or score trajectory
  were found on Titan.
- Integrated into: only the negative provenance note in `performance/LOG.md`
  and the null-tier cut decision. Titan's unrelated replay-debugging material
  was not retained as active CrewRift guidance.

The raw machine-specific directories were removed from the PR after integration
so reviewers load one package. Generated per-machine review pages remain here
for source review.
