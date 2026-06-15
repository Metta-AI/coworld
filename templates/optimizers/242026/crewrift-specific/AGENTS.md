# AGENTS.md — crewrift / notsus player optimization (always-on)

This is the **project tier** of a three-tier package — the irreducibly crewrift residue. It carries
the concrete numbers, league/division IDs, `notsus.nim`/`sim.nim` line cites, the measured-dead
levers, and the actual commands. The methodology that produced them lives one tier up:

- **General measurement / iteration / fail-loud discipline → generic tier** (`../generic/AGENTS.md`).
- **Coworld eval, promotion, roster-resolution, classify-before-porting, version-roll, keep-loop-alive
  methodology → coworld-player tier** (`../coworld-player-generic/AGENTS.md`).

An agent on crewrift loads ALL THREE tiers, so this file does NOT restate those principles — it states
the crewrift application and points up for the *why*. Read this every session before touching the bot.
The concrete working loop — orient → pick lever → root-cause → edit Nim → build/upload → server-side
A/B → verdict → ship/refute → record — is **LOOP.md** (its generalized shape is the coworld tier's
`coworld-optimization-loop.md`). Recurring recipes are **skills/**; deeper crewrift reference is
**guides/**; harness code is **tools/**; the measured-result ledger is **performance/LOG.md**.

The bot is the **notsus** scripted player (`notsus.nim` + `advisor.py`, branch
`daveey/crew-vote-gate`, crewrift 0.1.36). Its source lives in a **separate nested git repo**
(clone of `Metta-AI/coworld-crewrift`) inside the `daveey/crewrift` harness repo.

## The crewrift scoring & win model (the concrete numbers)

(Why the win model gates every hypothesis → coworld-player tier; these are the crewrift facts to keep
loaded.)

- **6 of 8 seats are crew.** Crew correctness dominates the leaderboard mean; an imposter improvement
  touches only ~25% of seats.
- **The game ends at imposter PARITY**, not "4 kills": `sim.nim checkWinCondition` fires when
  `aliveImposters >= aliveCrewmates`. With 2 imposters and 6 crew that is **4 of 6 crew REMOVED**,
  where a removal is a KILL **or** a vote-EJECTION — a wrongful ejection counts exactly like a kill,
  so meetings are double-edged. Crew win only if **all tasks finish first** (`allTasksDone`).
- **The field flips between task-decided and vote-decided.** In strong-field crew games kills are
  often 0 and the game ends on task completion (the deduction/vote path has no leverage); against a
  kill-heavy imposter the lever is kill-suppression. Pick the lever for the field you measured.
- **Leaderboard rank = lifetime `mean_round_score`** (one entry per player, large-n, slow-moving).
  Each league round is itself a mean over several mixed-role episodes, so top bots sit at only
  **~58–60** even though an isolated crew game scores ~104 (+100 win). Durable rank is **time-gated,
  not code-gated** once strong; the forced top-7 A/B isolates a single change but does NOT linearly
  predict the league mean — judge attribution from A/B deltas, position only from accumulated rounds.

## "Champion" is a slot label, not a ranking (the crewrift specifics)

(The general slot-label-isn't-quality misread → coworld-player tier; the crewrift bindings:)

- **"Champion" = the leaderboard-SCORING slot (`is_champion`), NOT winner / #1.** Each user has two
  players (experiment + champion). Judge any policy by **mean round score vs the field**, never the
  membership label.
- Official rank = `get_division_leaderboard(Competition div_8d3ead22-…)`, lifetime `mean_round_score`.
- The Competition board lists only players WITH a champion; roster churn can silently clear
  `is_champion` and delist you — after any roster change, verify and re-POST. See skill
  `resolve-live-roster-and-champion-state`.

## Verify before porting — most rival techniques are ALREADY in notsus.nim

(The classify-before-porting method → coworld-player tier; the crewrift fact that makes it acute:)

notsus already implements log-odds suspicion, witnessed-kill/vent confirmation, exact-TSP /
clearance-aware A* routing, isolated-victim + trajectory-intercept + unwitnessed-kill imposter play,
the recruitment-cascade chat, and the LLM advisor — **the crewborg "techniques to port" list is
largely STALE.** Read `guides/notsus-bot-architecture.md` (the already-implemented inventory) before
proposing any port, and measure the existing fire-rate first: several "missing" techniques fire
0/anywhere once instrumented (the Tier-1 deduction port did not move crew win rate — crew games are
task-decided). A cheap causal probe is the `buttonCalls: 0` config-ablation (one n=30/arm run proved
a rival's entire 41%-vs-18% edge was a single button press).

## Crewrift-specific guardrails

- **The open crew levers** that remain after all the refutations are in
  `guides/crew-strategy-and-open-levers.md`; the banked **refuted levers** (do not rebuild) are in
  `guides/refuted-levers-do-not-rebuild.md` and `performance/LOG.md`. Both are crewrift-measured —
  check them before proposing any crew change.
- **Bedrock model pin:** bake `CREWRIFT_BEDROCK_MODEL=us.anthropic.claude-sonnet-4-6` into the image
  ENV — the advisor's default opus model is not enabled in the runner account and dies silently
  (the bot becomes a pure skip-bot with a clean-looking results.json). See skill
  `diagnose-llm-advisor-health` and `build-and-upload-policy`.
- **`coworld upload-policy` is broken** (0.1.16+: server moved ECR push to an `authorization_token`).
  Use the manual ECR upload path in skill `build-and-upload-policy`.
- **The authoritative death/movement/vote oracle is the decoded replay**, not telemetry: download the
  `.bitreplay` and re-simulate with `tools/replay_mine.nim`. Server `results.json` and crewborg's
  trace.db are matched observers, not ground truth. See skill `decode-replay-ground-truth`.
- **When the coworld version rolls** (e.g. 0.1.24 → 0.1.36), run the migration in
  `guides/coworld-version-roll-migration.md` and diff the `sim.nim` scoring constants before trusting
  any prior number — then return to the loop.
- **Loop state lives in one private Asana project** ("Crewrift Policy Optimization", Crux Games +
  Improvement Ideas sections) with the verbatim reproduction config per crux; see
  `guides/crux-loop-and-asana-state.md`. The exact request-body / league-API shapes are in
  `guides/experience-request-and-league-api-reference.md`.
- **Watch loops must use a persistent Monitor**, never a detached Bash `run_in_background` with a long
  foreground `sleep` (it dies silently mid-loop: 0-byte logfile, no verdicts). See skill
  `watch-and-monitor-with-poller`. (session-derived, unverified)
- The post-2026-06-12 `roster` request body (one entry per seat, `policy_ref`) replaced the old
  requester/opponents shape, which now 422s; opponents land in **list order**, so verify seat
  assignment by `participants[].position`, never by pvid uniqueness. (session-derived, unverified)
