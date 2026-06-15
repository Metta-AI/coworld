# MANIFEST — crewrift-specific (project tier)

The irreducible crewrift residue of the three-tier player-optimization package. Every item here
carries concrete crewrift facts (numbers, league/division IDs, `notsus.nim`/`sim.nim` line cites,
the measured-dead levers, the actual commands). The general principle each item *applies* lives one
tier up and is cited in the right-hand column — this tier never restates it.

Tier map: **generic** (`../generic`) = pure software-optimization discipline · **coworld-player**
(`../coworld-player-generic`) = methodology for optimizing any player for any Softmax coworld league ·
**crewrift-specific** (this package) = the one game's instance.

## Always-on framing

| Item | What it carries (crewrift-specific) | General principle it applies (tier 2/3) |
| --- | --- | --- |
| `AGENTS.md` | The keep-loaded crewrift facts: 6/8 crew + parity win model + `sim.nim checkWinCondition` + ~58–60 league mean; champion=`is_champion` slot + Competition division ID + `get_division_leaderboard`; "most rival techniques already in `notsus.nim`"; Bedrock pin, broken `upload-policy`, replay oracle, version-roll, Asana state, Monitor-not-Bash, roster body schema. | Win-model / slot-label / classify-before-porting / fail-loud → coworld-player AGENTS.md. Measurement & iteration discipline → generic AGENTS.md. |
| `LOOP.md` | The concrete crewrift working loop end-to-end: exact commands, source paths (`notsus.nim`, `sim.nim`, `server.nim`), failure-handling sub-loops, observed human steers, superseded eval rungs. | Generalized loop SHAPE → coworld-player `guides/coworld-optimization-loop.md`; measure/fail-loud rationale → generic AGENTS.md. |

## Performance ledger

| Item | What it carries (crewrift-specific) | General principle it applies (tier 2/3) |
| --- | --- | --- |
| `performance/LOG.md` | The measured-result ledger: every crewrift A/B win and refutation with its numbers, config, and verdict (the banked negatives so a dead lever is never rebuilt). | "A refutation is a result" / extend-don't-re-roll / CI verdicts → generic AGENTS.md + `guides/measurement-and-iteration-discipline.md`. |

## Guides (on-demand crewrift reference)

| Item | What it carries (crewrift-specific) | General principle it applies (tier 2/3) |
| --- | --- | --- |
| `guides/notsus-bot-architecture.md` | The already-implemented `notsus.nim` inventory + code map (A*/TSP routing, log-odds suspicion, witnessed-kill/vent, imposter play, LLM advisor) — read before any port. | Read-your-own-bot-first / classify-before-porting → coworld-player AGENTS.md; don't-copy-for-payoff → generic AGENTS.md. |
| `guides/crew-strategy-and-open-levers.md` | The crewrift crew win-model and the still-open vs exhausted crew levers, with expected value per remaining lever. | Descend-one-causal-layer → generic AGENTS.md; field-regime lever choice → coworld-player AGENTS.md. |
| `guides/refuted-levers-do-not-rebuild.md` | The catalog of crewrift crew-side ideas MEASURED and refuted (with N≥30/arm numbers); burden-of-proof rules before re-proposing one. | Refutations-are-results → generic AGENTS.md. |
| `guides/crux-loop-and-asana-state.md` | The 4-stage resumable crewrift crux loop and how its state lives in the one Asana project (sections, verbatim request JSON, attribution line). | Keep-loop-alive + checkpoint-state → generic/coworld-player AGENTS.md; crux mechanics → coworld `guides/coworld-league-eval-methodology.md`. |
| `guides/experience-request-and-league-api-reference.md` | Exact crewrift/Observatory shapes: auth handshake, post-2026-06-12 `roster` body, constants, artifact routes, timeout formula, player-artifact upload/download contract. | Server-side counterfactual-match engine → coworld-player AGENTS.md. |
| `guides/coworld-version-roll-migration.md` | The one-time-per-roll crewrift migration: detect the coworld-ID mismatch, re-download, diff `sim.nim` scoring constants, re-baseline. | "When the package rolls, run the migration before trusting numbers" → coworld-player AGENTS.md. |

## Skills (on-demand crewrift recipes)

| Item | What it carries (crewrift-specific) | General principle it applies (tier 2/3) |
| --- | --- | --- |
| `skills/run-league-ab-eval` | The standard candidate-vs-baseline (or crux/swap-arm) A/B on the hosted league via experience-requests, forced-role seat, Wilson verdict. | CI-verdict / extend-and-pool → generic; server-side eval + live-mix replica gate → coworld-player. |
| `skills/build-and-upload-policy` | Compile a `notsus.nim` change to an amd64 image (build/validation ladder, local full-container gate) + the MANUAL ECR upload replacing the broken `coworld upload-policy`. | Minimal-change / one-variant-one-build → generic AGENTS.md. |
| `skills/resolve-live-roster-and-champion-state` | Resolve live pvids, audit the FULL roster, restore the `is_champion` flag before launch / after churn / on delist. | Re-resolve-live-state / slot-label-isn't-quality → coworld-player AGENTS.md. |
| `skills/decode-replay-ground-truth` | Authoritative per-slot deaths/survival/movement/reward/role/tasks by re-simulating the S3 replay with `replay_mine`. | Terminal/ground-truth evidence over telemetry → coworld-player `guides/cross-coworld-craft.md`. |
| `skills/generate-a-crux` | Hunt + Wilson-confirm a crewrift crux (config where a rival reproducibly out-scores you at a fixed role/seat), or rule it out as variance. | Reconstruct-before-you-believe / pool same-direction deficits → generic; crux construction → coworld-player. |
| `skills/diagnose-llm-advisor-health` | Confirm the notsus Bedrock vote advisor is firing before trusting any advisor-sensitive result (silent skip-bot failure mode). | Distinguish infra failure from a real negative → generic AGENTS.md. |
| `skills/diagnose-stuck-or-failed-run` | Classify a dead/empty/wedged eval or zero-score round as infra vs real result (buffering, backend down, auth/route skew, wedged participant). | Distinguish infra failure from a real negative; named negative controls → generic / coworld-player. |
| `skills/watch-and-monitor-with-poller` | The standing watch loop that survives turns — drive it with a persistent Monitor, NOT detached Bash + foreground sleep (dies silently). | Background-processes-die-silently / keep-loop-alive → generic AGENTS.md. |

## Tools (verbatim harness code)

| Item | What it carries (crewrift-specific) | General principle it applies (tier 2/3) |
| --- | --- | --- |
| `tools/` (+ `SOURCES.md`, per-file `.note.md`) | The executable crewrift eval stack copied verbatim from `daveey/crewrift` (`eval.py`, `league_eval.py`, `league_roster.py`, `harness_core.py` Wilson math, `metrics.py`, `episode_runner.py`, `run_index.py`, `monitor.py`, `antfarm_run.py`, `dashboard.py`, `render.py`, `softmax_pull.py`) and `Metta-AI/coworld-crewrift` (`advisor.py`, `replay_mine.nim`, `Dockerfile.llm`), with provenance map. | The Wilson verdict / server-side A/B / live-mix-replica machinery these implement → generic + coworld-player. |
