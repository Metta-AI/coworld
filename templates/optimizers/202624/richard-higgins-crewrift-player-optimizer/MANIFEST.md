# MANIFEST

This package is the integrated output of four machine-specific extraction runs.
Direct CrewRift optimizer findings came from `zephyrus`, `xpser`, and `mbp`;
`titan` was reviewed and retained only as process provenance because it did not
contain direct CrewRift optimizer findings.

- `AGENTS.md`: always-on CrewRift optimizer operating rules distilled from the
  direct CrewRift packages.
- `LOOP.md`: the integrated optimization loop, merging co-gas remote XP,
  player-labs RelhAlpha onboarding, and the Titan non-CrewRift gap.
- `performance/LOG.md`: concrete policy trajectory notes and gaps.
- `universal/`: all learnings before tier subtraction.
- `crewrift-specific/`: CrewRift-only mechanics and social-policy lessons.
- `remote-xp-optimizer-loop/`: co-gas and hosted-XP workflow lessons.
- `generic/`: fully general evidence-first optimization lessons.
- `source-machines/INDEX.md`: concise provenance for machine-specific source
  packages and cut decisions.
- `source-machines/review-*.html`: generated source-review pages from each
  machine run.
- `null-tier.md`: reviewed content that did not survive integration.

The previous machine-specific package directories were removed after their
useful findings were integrated here.
