# MANIFEST — crewrift player optimization package

One row per package item. **type** is the item's role in the package:
`always-on` (loaded every session), `skill` (on-demand recipe), `guide`
(reference reasoning), `loop` (the working cycle), `performance` (the appendable
result log), `tool` (executable harness code).

"Sources merged" lists the haul/memory files each item was built from (paths are
shortened: `mem/X` = `~/.claude/projects/-Users-daveey-code-crewrift/memory/X.md`;
`ext/X` = `haul/from-files/extracted/X.md`; `sess/X` = `haul/from-sessions/X.md`;
`docs/X` = `haul/from-files/docs/X.md`, cited as a verbatim reference SOURCE, not
routed as a corpus item). Items carrying session-derived (`sess/…`) or any
explicitly `(session-derived, unverified)`-tagged content are marked
**(unverified)** — they are strong priors that have not been independently
re-confirmed against source this pass.

"Conflicts resolved" records any in-package supersession.

---

## Top-level framing and loop

| item | type | what it is | sources merged | conflicts resolved |
|---|---|---|---|---|
| `AGENTS.md` | always-on **(unverified)** | The standing guardrails that shape every hypothesis: scoring/parity/lifetime-mean win model; "champion = slot label not rank"; N≥30 Wilson discipline; the two-slot live A/B + promotion rule; re-resolve-live-state-every-launch; fail-loud / no caching; keep-loop-alive + league-actions-gated; verify-before-porting. | mem/crewrift-parity-win-model, mem/crewrift-league-score-model, ext/crew-correctness-over-imposter-cleverness, mem/crewrift-champion-is-leaderboard-slot, ext/wilson-ci-verdict-discipline, sess/power-discipline-beyond-n30, mem/crewrift-kyle-pooled-crux, ext/two-player-slots-experiment-and-champion, ext/windowed-z-gate-cannot-fire-promotion, ext/live-mix-replica-arms-before-fielding, mem/crewrift-roster-churns-mid-session, sess/era-baselines-rot-within-hours, ext/forced-slots-no-fallback-fail-loud, sess/optimization-loop-liveness-heartbeat, mem/crewborg-techniques-to-copy, sess/copied-behaviors-dont-carry-their-payoff | `crewborg-techniques-to-copy` carried here as the **stale "to-port" list to distrust** (verify-before-porting section); its concrete already-implemented refutations live in `guides/notsus-bot-architecture.md`. `live-mix-replica-arms-before-fielding` is shared with `skills/generate-a-crux` (always-on gate vs concrete Stage-3 construction). |
| `LOOP.md` | loop **(unverified)** | The end-to-end working cycle (orient → pick lever → root-cause → edit Nim → build/upload → server-side A/B → verdict → ship/refute → record), plus the recurring failure-handling sub-loops, the human's standing steers, and the two deliberately-replaced eval rungs kept as history. | Reconstructed across the campaign sessions; the procedural backbone is also captured in `guides/crux-loop-and-asana-state` (docs/optimize-policy + ext/crux-loop-stages-and-asana-state). Cross-cuts most skills/guides. | Self-marks **two superseded eval rungs** (local docker A/B; the dqueue Aurora/EC2 runner fleet) as history — do not resurrect. Notes memory supersedes stale playbook sections. |
| `performance/LOG.md` | performance | Appendable per-period performance log: one dated entry (coworld, policy lineage, start/end rank, trajectory, score-comparability caveats). Seeded with the 2026-06-05→06-12 optimization period. | Synthesized from the campaign's measured results (the same result-notes routed into the refuted-levers + crew-strategy guides and the score-model AGENTS section). | — |

## Skills (`skills/<name>/SKILL.md`)

| item | type | what it is | sources merged | conflicts resolved |
|---|---|---|---|---|
| `run-league-ab-eval` | skill **(unverified)** | The standard "did my change help?" A/B: candidate vs baseline (or a crux/swap arm) via server-side Observatory experience-requests, forced-role seat + top-7 field, Wilson verdict. Carries the post-2026-06-12 unified `roster` body schema. | ext/xreq-roster-body-schema-2026-06-12, mem/crewrift-xreq-roster-api-change, mem/crewrift-league-eval-server-side, ext/experience-request-timeout-budget, sess/ab-arm-image-hygiene, mem/crewrift-ereq-parallelism | Dedupe-merge: `crewrift-xreq-roster-api-change` merged with `xreq-roster-body-schema-2026-06-12` (one roster-schema statement); `crewrift-ereq-parallelism` merged with `experience-request-timeout-budget` (one parallelism/timeout statement). |
| `build-and-upload-policy` | skill **(unverified)** | Compile a notsus.nim change to an amd64 image and upload it as a new policy version via the MANUAL ECR `authorization_token` path (the `coworld upload-policy` CLI is broken in 0.1.16+); includes the build/validation ladder and local full-container gate. | sess/notsus-build-validation-ladder, mem/crewrift-ecr-upload-authtoken, sess/upload-policy-null-presign-and-alias, ext/local-full-container-gate-before-upload, sess/cert-fixture-smoke-false-alarms, sess/policy-repo-layout-and-push-targets | — |
| `decode-replay-ground-truth` | skill **(unverified)** | Get authoritative per-slot deaths/survival/movement/reward by re-simulating the recorded S3 replay with the `replay_mine` binary, instead of trusting telemetry. | ext/replay-mine-oracle-csv-schema, mem/crewrift-crewborg-artifact-observer, ext/replay-watching-hosted-vs-local-vs-raw, ext/per-episode-artifact-routes-results-logs | Self-marks the crewborg `trace.db` observer and server `results.json` as **matched observers superseded by the replay oracle** for per-slot death/movement. Flags `tools/antfarm_run.py` as superseded (pre-rework xreq body). |
| `generate-a-crux` | skill **(unverified)** | Hunt for and Wilson-confirm a crux game (a config where a rival reproducibly outscores you), from a league round or your own past episode (swap tournament), with pooling and the deterministic-seed caveat. | ext/swap-tournament-from-own-past-episodes, ext/seed-is-real-config-key-reproducibility, mem/crewrift-recon-sweep-optimizer-sole-crux, ext/live-mix-replica-arms-before-fielding, ext/top-n-vs-random-roster-fill-tradeoff, ext/top-n-champion-pool-empty-rank-from-rounds, mem/crewrift-buttoncalls-config-key | `live-mix-replica-arms-before-fielding` shared with `AGENTS.md` (the concrete Stage-3 construction lives here). |
| `diagnose-stuck-or-failed-run` | skill **(unverified)** | Classify a dead/empty/wedged/failed-or-zero eval run as INFRA vs POLICY before reverting — buffering, uv-preamble JSON corruption, backend/dispatch, empty-leaderboard trap, teardown race, API-shape drift. | sess/detached-eval-output-buffering, sess/antfarm-backend-unreliable-use-k8s, ext/failed-round-is-not-always-a-policy-crash, sess/empty-leaderboard-traps, **sess**/conform-to-deployed-openapi-not-local-models, ext/wrap-player-process-in-timeout-so-results-write-before-teardown | Plan listed `conform-to-deployed-openapi-not-local-models` under an `ext/` path; the file actually lives at `sess/` — same content, Branch F. See Coverage note 1. |
| `diagnose-llm-advisor-health` | skill **(unverified)** | Confirm the LLM (Bedrock) vote advisor is actually firing before trusting any advisor-sensitive result; the dead-advisor signature lives only in per-agent logs, not `results.json`. Carries the vote-conversion root cause and the 150-tick deadline tradeoff. | sess/llm-advisor-health-invalid-skip-signature, sess/llm-vote-deadline-150-tradeoff, mem/crewrift-vote-conversion-defect, ext/dont-fire-blind-controlled-rounds-when-local-ab-nondeterministic | Dedupe: `crewrift-vote-conversion-defect` placed HERE (dead-advisor root cause) rather than the refuted-levers guide, where its tier8-10 "lane closed" chain overlaps `crewrift-perception-presence-not-recall` — same finding, stated once. |
| `resolve-live-roster-and-champion-state` | skill **(unverified)** | Before any launch / after any churn / when a player vanishes from standings: re-resolve live pvids, audit the FULL (name-unfiltered) roster, and restore the `is_champion` flag. | sess/membership-churn-clears-champion-flag, sess/fresh-player-ledger-reset, ext/coworld-api-client-auth-and-raw-http | — |
| `watch-and-monitor-with-poller` | skill **(unverified)** | Any standing watch loop (crux battery, league rounds, rank watch) must run via a persistent Monitor poller, NOT a detached Bash background + foreground `sleep` (which dies silently mid-loop). | mem/crux-scout-poller-monitor, mem/crewrift-watch-loop-needs-monitor, sess/dashboard-instance-staleness-gotchas, sess/harness-tests-run-with-unittest | — |

## Guides (`guides/<name>.md`)

| item | type | what it is | sources merged | conflicts resolved |
|---|---|---|---|---|
| `refuted-levers-do-not-rebuild` | guide **(unverified)** | The banked ledger of MEASURED dead ends so they are never rebuilt (presence, Tier-1 deduction, proactive press, tier6e press tuning, recall-expansion/vote-cursor, track-memory victim-link, sprite-recall), each with its numbers + the descend-one-causal-layer method. | mem/crewrift-presence-lever-refuted, mem/crewrift-tier1-deduction-result, mem/crewrift-tier6e-press-result, mem/crewrift-tier9-perception-port-result, mem/crewrift-perception-presence-not-recall, sess/wrongful-votes-are-negative-value, mem/crewrift-imposter-ab-variance | **Supersedes: tier9 sprite-recall claim** — Lever 7 (`crewrift-perception-presence-not-recall`) explicitly supersedes the tier9 note's "gap is sprite-vision recall" (recall ≈0.77; bottleneck is PRESENCE). `tier9-perception-port-result` + `perception-presence-not-recall` co-located as ONE perception-lane refutation. |
| `notsus-bot-architecture` | guide **(unverified)** | The already-implemented inventory + code map of the notsus bot (per-tick `decideNextMask`, A*/coast nav, exact-TSP routing, log-odds suspicion, LLM vote chain, imposter prowl/intercept play, perception/self-ID, advisor subprocess, tunable constants) — read before proposing any port. | ext/notsus-per-tick-decision-architecture, ext/notsus-astar-clearance-and-coast-nav, ext/notsus-task-routing-tsp-with-detour-cap, ext/notsus-crew-suspicion-logodds-model, ext/notsus-crew-vote-evidence-chain, ext/notsus-imposter-hunt-search-prowl-already-implemented, ext/notsus-perception-localization-and-self-id, ext/notsus-llm-advisor-subprocess-architecture, ext/notsus-tunable-constants-reference, docs/optimize-policy | Holds the concrete refutations of the stale `crewborg-techniques-to-copy` list (which sits, as a list-to-distrust, in `AGENTS.md`). |
| `crew-strategy-and-open-levers` | guide **(unverified)** | The current strategic frontier: ghost routing (zero-risk task-win lever), TSP-beats-greedy only in the contested win band, the broad/near-optimal leaderboard gap with vote-conversion as the specific hole, truecrew replay-mining as the only remaining lever vs the private #1. | mem/crewrift-ghosts-complete-tasks, sess/tsp-task-routing-beats-greedy-under-pressure, mem/crewrift-leaderboard-gap-diagnosis, mem/crewrift-truecrew-replay-mining, sess/vote-fix-ladder-gate-pileon-recruitment | — |
| `crux-loop-and-asana-state` | guide **(unverified)** | The 4-stage resumable improvement loop (find / analyze / implement+validate / promote) and how its state lives in one Asana project — resume by reading sections, file a crux with the exact request JSON, link idea→crux deps, attribution line. | ext/crux-loop-stages-and-asana-state, docs/optimize-policy | Procedural backbone behind `LOOP.md` (LOOP adds the failure sub-loops + steers). |
| `experience-request-and-league-api-reference` | guide **(unverified)** | The Observatory/experience-request API reference: auth + raw-HTTP, key league/division/coworld constants, the post-2026-06-12 roster body schema, top_n-vs-random fill, Competition-empty workaround, artifact routes, timeout-budget formula, player-artifact upload/download contract. | docs/league-api, docs/league-eval-design-spec, ext/player-artifact-upload-download-contract, mem/crewrift-nim-artifact-curl-ssl, sess/emergency-button-mechanics | **Supersedes: pre-2026-06-12 wire-format** — marks the old `requester`/`opponents` request shape as superseded by the unified `roster` section (keeps the design rationale). |
| `coworld-version-roll-migration` | guide **(unverified)** | The once-per-roll procedure when the league bumps its coworld package: detect the live-vs-local ID mismatch, back up untracked patches, triage old patches against rewritten upstream, verify scoring constants survive, compat probe, port by symbol-grep. | sess/coworld-version-roll-migration-procedure | — |
| `cross-coworld-craft` | guide **(unverified)** | Generic transferable craft for any coworld/tournament league (from the sibling co-gas world): match the wire-protocol family not the commissioner key; gate across the full role/slot matrix; wait for terminal completed evidence; keep failed candidates as named negative controls; run two owned identities as blue/green lanes. | ext/match-the-worlds-protocol-family-not-the-commissioner-key, ext/validate-across-all-role-slot-cases-not-just-target, ext/wait-for-terminal-evidence-not-partial-or-single-round, ext/keep-failed-experiments-as-named-negative-controls, ext/two-owned-identities-as-swappable-lanes-dont-churn-rename | — |

## Tools (`tools/`)

Verbatim copies of the executable harness, each paired with a `<tool>.note.md`
provenance/usage note. Provenance for all of them is in `tools/SOURCES.md`
(maps each file to its origin repo path: `daveey/crewrift` `_harness/` for the
Python eval stack; `Metta-AI/coworld-crewrift` `players/notsus/` +
`src/crewrift/` for the bot-side files). These are copied artifacts, not distilled
from haul/memory notes, so they carry no "sources merged" row — `SOURCES.md` is
the authority. Listed individually for completeness:

| item | type | what it is | sources merged | conflicts resolved |
|---|---|---|---|---|
| `tools/SOURCES.md` | tool | Provenance table mapping every `tools/` file to its origin repo + path. | (authoring note over the two source repos) | — |
| `tools/eval.py` (+`.note.md`) | tool | CLI front door for the league A/B (`run_league_ab`). | origin `_harness/eval.py` (`daveey/crewrift`) | — |
| `tools/league_eval.py` (+`.note.md`) | tool | The A/B engine: builds the roster body, runs both arms concurrently, polls to terminal, computes the Wilson verdict. | origin `_harness/league_eval.py` | — |
| `tools/league_roster.py` (+`.note.md`) | tool | `live_members` / `fetch_top_players` — the authoritative live-pvid roster resolver. | origin `_harness/league_roster.py` | — |
| `tools/harness_core.py` (+`.note.md`) | tool | Shared core: `wilson(k,n)` verdict math, forced-slot / seed-deterministic role layout. | origin `_harness/harness_core.py` | — |
| `tools/metrics.py` (+`.note.md`) | tool | Offline per-episode diagnosis: win-rate, vote accuracy, where score is lost. | origin `_harness/metrics.py` | — |
| `tools/episode_runner.py` (+`.note.md`) | tool | Wraps an A/B for background/dashboard runs. | origin `_harness/episode_runner.py` | — |
| `tools/run_index.py` (+`.note.md`) | tool | The per-checkout run index (`league_runs.json`) backing the dashboard. | origin `_harness/run_index.py` | — |
| `tools/monitor.py` (+`.note.md`) | tool | The canonical poller shape (snapshot + print-only-on-change) you arm Monitor with. | origin `_harness/monitor.py` | — |
| `tools/antfarm_run.py` (+`.note.md`) | tool **(superseded)** | Artifact harvester (results.json + replays per episode). | origin `_harness/antfarm_run.py` | **Note marks it SUPERSEDED** — `build_request` emits the pre-2026-06-12 request shape and 422s until patched to the unified `roster` body. |
| `tools/dashboard.py` (+`.note.md`) | tool **(superseded role)** | Local docker-A/B dashboard. | origin `_harness/dashboard.py` | **Note marks its role superseded** — retained only as a cheap mechanism-check lab (not league-faithful); the server-side eval replaced it. |
| `tools/render.py` (+`.note.md`) | tool | Renders the single-file dashboard HTML/JS at server boot. | origin `_harness/render.py` | — |
| `tools/softmax_pull.py` (+`.note.md`) | tool | Pulls division leaderboards / rounds / submissions from the endpoints that work today (coerces null leaderboard to `[]`). | origin `_harness/softmax_pull.py` | — |
| `tools/advisor.py` (+`.note.md`) | tool | The out-of-process Bedrock LLM vote advisor (stdin snapshot → `{"vote","chat"}`). | origin `players/notsus/advisor.py` (`Metta-AI/coworld-crewrift`) | — |
| `tools/replay_mine.nim` (+`.note.md`) | tool | The replay re-sim oracle (per-slot `slot,role,reward,tasks,alive,diedTick,dist` CSV). | origin `src/crewrift/replay_mine.nim` | — |
| `tools/Dockerfile.llm` (+`.note.md`) | tool | The amd64 build Dockerfile (with LLM advisor) used to produce policy images. | origin `players/notsus/Dockerfile.llm` | Note records that `coworld upload-policy` is broken so the built image goes via the manual ECR push. |

---

## Coverage

Verification of all **87** corpus source files across the three classes
(`mem/*` excl. MEMORY.md = 26; `sess/*` excl. `_dropped.json` = 24; `ext/*` = 37)
against the package items above + `null-tier.md`.

**Result: 86 routed into package items, 1 cut, 0 content-orphaned.** Every source
landed somewhere. The three `docs/*` files (`optimize-policy`, `league-api`,
`league-eval-design-spec`) are verbatim reference SOURCES cited into the guides,
not corpus items, and are not counted in the 87.

### Sources that landed NOWHERE (routing bugs)

**None.** No corpus file is unaccounted for. There is, however, one source-path
discrepancy in the routing plan to flag (it is not an orphan — the content IS
routed):

1. **`conform-to-deployed-openapi-not-local-models.md` — directory mislabel in
   the plan, not an orphan.** The plan's `diagnose-stuck-or-failed-run` skill
   listed this file under the **`ext/`** (`haul/from-files/extracted/`) path, but
   the file actually exists only under **`sess/`**
   (`haul/from-sessions/conform-to-deployed-openapi-not-local-models.md`); there
   is no `ext/` copy. The content was consumed correctly — it is the
   `diagnose-stuck-or-failed-run` skill's **Branch F (API shape drift / 422 →
   conform to the deployed OpenAPI)**. So the file is routed and accounted for;
   only its source-class label in the plan is wrong (it is a session-derived
   source, which is consistent with the skill being marked **(unverified)**). No
   action needed beyond this note; recorded so the discrepancy isn't mistaken for
   missing coverage.

### Cut (see `null-tier.md`)

- **`ext/game-docs-are-empty-stubs.md`** — pure negative marker that six
  `docs/game-*.md` files are 0-byte stubs; its only payload (go to Nim source /
  memory notes for the real game model) is already implied by every guide that
  cites `sim.nim`/`global.nim` and the parity/score notes. 1 of 1 cut.

### Notes on intentional dedupe-merges (not orphans, not cuts)

These corpus files are routed once and referenced (not double-listed as items):
`crewrift-xreq-roster-api-change` ↔ `xreq-roster-body-schema-2026-06-12` and
`crewrift-ereq-parallelism` ↔ `experience-request-timeout-budget` (both merged
inside `run-league-ab-eval`); `crewrift-vote-conversion-defect` placed in
`diagnose-llm-advisor-health`; `crewrift-tier9-perception-port-result` +
`crewrift-perception-presence-not-recall` co-located in `refuted-levers`;
`live-mix-replica-arms-before-fielding` cited in BOTH `AGENTS.md` and
`generate-a-crux`; `crewborg-techniques-to-copy` placed in `AGENTS.md` as the
stale list-to-distrust with its refutations in `notsus-bot-architecture`. The
`MEMORY.md` index is the implicit dedupe parent and is not separately routed —
every one of its lines maps to a routed detail note.
