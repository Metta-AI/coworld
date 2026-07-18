# REVIEW — crewrift player-optimizer package (jboggs)

This package was reviewed phase-by-phase during extraction (sessions & loop → file haul →
universal package → tier split) via a hosted `review.html` with per-chunk comment capture.
That HTML index (~18 MB) is intentionally **not** committed: it is a build/review artifact, not
package content, and its embedded game-state strings (e.g. inventory fields like
`hp/energy/hearts/cargo`) trip repo secret-scanners as false positives.

## How to read this package

- Start at `METADATA.md` (what this is) and `AGENTS.md` (orientation).
- `MANIFEST.md` in each tier lists its contents.
- Load the tier that matches your task: `crewrift-specific/`, `optimization-loop-specific/`, `generic/`,
  or `universal/` for everything.
- `LOOP.md` is the optimization loop; `performance/LOG.md` is the crewborg trajectory;
  `null-tier.md` records cuts and the tier-split audit.

## Regenerating the HTML review surface

The review page is reproducible from the source-side tooling (`make_review.py` over the haul/records
on the originating machine). It is not required to consume the package.
