# TIERS — the three-tier player-optimization package

This package is split into **three nested tiers** by generality. The split is **subtraction, not
duplication**: each principle is stated once, in the most general tier it is true for; the more
specific tiers carry only their own additions (an application, a number, a command) and POINT up for
the rationale. No statement appears in two tiers.

The source of truth these tiers were factored out of is `universal/` — the original undivided package.

```
generic (tier 3)
  └─ coworld-player-generic (tier 2)
       └─ crewrift-specific (tier 1)
```

Each outer tier is loadable on its own; each inner tier assumes the tiers above it are also loaded.

## The three tiers

| Tier | Directory | For | Mentions |
| --- | --- | --- | --- |
| 3 — generic | `generic/` | ANY coding-agent / software-optimization work. Pure discipline: measuring a change, reading a noisy signal, debugging a behavior that won't fire, deciding whether to ship. | No game, league, vendor, or project — reads coherently alone. |
| 2 — coworld-player | `coworld-player-generic/` | Optimizing ANY scripted/LLM player for ANY Softmax **coworld** league (a different game, a different bot). The hosted-league methodology: server-side eval, forced-role A/B, cruxes, promotion gates, roster resolution, version rolls. | The coworld *shape* only — no specific game, IDs, numbers, or commands; points to "the project tier" for those. |
| 1 — crewrift-specific | `crewrift-specific/` | Optimizing the **notsus** bot for the **crewrift** coworld league. The irreducible residue: concrete numbers, league/division IDs, `notsus.nim`/`sim.nim` line cites, measured refuted levers, actual commands, the executable harness, the performance log. | All the crewrift specifics; points up to tiers 2/3 for every general principle. |

## Which agent loads which combination

| Agent | Loads |
| --- | --- |
| **crewrift agent** (optimizing notsus on crewrift) | **all three** — tier 1 + tier 2 + tier 3 |
| **other-coworld agent** (a different Softmax coworld game/bot) | **tier 2 + tier 3** (writes its own tier 1) |
| **generic agent** (any optimization / coding-agent task) | **tier 3 alone** |

Tier 1 deliberately does **not** restate the general principles — it carries the crewrift application
and points to tier 2 / tier 3 for the why. An agent on a different coworld game gets a complete,
coherent methodology from tier 2 + tier 3 without any crewrift residue.

## File index per tier

### Tier 3 — `generic/`
- `AGENTS.md` — always-on generic guardrails (iteration loop, measure-don't-vibe, precision-before-recall, descend-a-layer, classify-before-porting, fail-loud, keep-loop-alive, gate-outward-actions, working-tree hygiene).
- `guides/measurement-and-iteration-discipline.md` — the long-form ten-section reference behind the AGENTS core.
- `MANIFEST.md` — per-file map + the universal sources each file generalizes.

### Tier 2 — `coworld-player-generic/`
- `AGENTS.md` — always-on coworld-player guardrails (server-side eval premise, the four scoring facts to pin, slot-label-isn't-quality, two-slot A/B + promotion, re-resolve-live-state, fail-loud-on-forced-seat, verify-before-porting).
- `guides/coworld-league-eval-methodology.md` — the server-side forced-role A/B + crux + ground-truth + promotion + roster-resolution + version-roll methodology (shapes, not commands).
- `guides/coworld-optimization-loop.md` — the command-free 8-stage loop shape + standing ground rules + failure-handling sub-loops.
- `guides/cross-coworld-craft.md` — cross-league craft (protocol-family matching, full role/slot gate, terminal evidence, named negative controls, blue/green lanes).
- `MANIFEST.md` — per-file map + the universal sources each file generalizes.

### Tier 1 — `crewrift-specific/`
- `AGENTS.md` — always-on crewrift facts (parity win model + `sim.nim checkWinCondition`, ~58–60 league mean, champion=`is_champion` + Competition division ID, "rival techniques already in notsus.nim", Bedrock pin, current `upload-policy`, replay oracle, version-roll, Asana state, Monitor-not-Bash, roster body schema).
- `LOOP.md` — the concrete crewrift working loop end-to-end (exact commands, source paths, sub-loops, human steers); points to tier 2's loop shape.
- `performance/LOG.md` — the appendable measured-result ledger (every A/B win and refutation with numbers).
- `guides/notsus-bot-architecture.md` — the already-implemented notsus inventory + code map (read before any port).
- `guides/crew-strategy-and-open-levers.md` — the crew win-model and still-open vs exhausted crew levers.
- `guides/refuted-levers-do-not-rebuild.md` — the banked crewrift refuted-lever ledger (with N≥30 numbers).
- `guides/crux-loop-and-asana-state.md` — the 4-stage resumable crux loop and its Asana state.
- `guides/experience-request-and-league-api-reference.md` — exact Observatory/experience-request shapes, constants, artifact routes, timeout formula.
- `guides/coworld-version-roll-migration.md` — the one-time-per-roll crewrift migration.
- `skills/` — recurring crewrift recipes (`run-league-ab-eval`, `build-and-upload-policy`, `resolve-live-roster-and-champion-state`, `decode-replay-ground-truth`, `generate-a-crux`, `diagnose-llm-advisor-health`, `diagnose-stuck-or-failed-run`, `watch-and-monitor-with-poller`).
- `tools/` — the executable crewrift eval stack copied verbatim (+ `SOURCES.md` provenance, per-file `.note.md`).
- `MANIFEST.md` — per-file map (item → crewrift specifics → the tier-2/3 principle each applies).
