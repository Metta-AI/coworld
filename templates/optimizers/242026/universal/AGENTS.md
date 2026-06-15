# AGENTS.md — crewrift player optimization (always-on)

This package is the standing knowledge base for optimizing the **notsus** scripted bot
(`notsus.nim` + `advisor.py`) for the Crewrift Coworld league. Read this every session before
touching the policy. The working loop — orient → pick lever → root-cause → edit Nim → build/upload →
server-side A/B → verdict → ship/refute → record — lives in **LOOP.md**; execute it from there.
Recurring how-to recipes live in **skills/** (`run-league-ab-eval`, `build-and-upload-policy`,
`resolve-live-roster-and-champion-state`, `decode-replay-ground-truth`,
`watch-and-monitor-with-poller`). Deeper reference reasoning that is neither always-on nor a recipe
lives in **guides/**. Executable harness code lives in **tools/**. This file is only the framing and
guardrails that shape *every* hypothesis — keep it loaded; everything else is on-demand.

## The scoring & win model

Every hypothesis is shaped by how the game and leaderboard actually score.

- **6 of 8 seats are crew**, so crew correctness dominates the leaderboard mean. An imposter
  improvement only touches ~25% of seats — crew correctness beats imposter cleverness on average.
- **The game ends at imposter PARITY**, not "4 kills": `sim.nim checkWinCondition` fires when
  `aliveImposters >= aliveCrewmates`. With 2 imposters and 6 crew that is **4 of 6 crew REMOVED**,
  where a removal is a KILL **or** a vote-EJECTION. A wrongful ejection counts the same as a kill —
  meetings are double-edged. Crew win only if **all tasks finish first** (`allTasksDone`).
- **The field flips between task-decided and vote-decided**, so the lever depends on the field. In
  strong-field crew games kills are often 0 and the game ends on task completion (the deduction/vote
  path has no leverage); against a kill-heavy imposter the lever is kill-suppression. Pick the lever
  for the field you measured, not in the abstract.
- **Leaderboard rank = lifetime `mean_round_score`** (one entry per player, large-n, slow-moving).
  Each league "round" is itself a mean over several mixed-role episodes (crew + imposter + losses),
  so top bots sit at only ~58–60 even though an isolated crew game scores ~104. Durable rank is
  **time-gated, not code-gated** once the bot is strong. The forced top-7 A/B isolates a single
  change but does NOT linearly predict league mean — judge attribution from A/B deltas, position
  only from accumulated rounds.

## "Champion" is a slot label, not a ranking

The single most-repeated misread. **"Champion" = the leaderboard-SCORING membership slot
(`is_champion`), NOT winner / #1.** Each user has two players (experiment + champion).

- Judge any policy by **mean round score vs the field**, never the membership label.
- Official rank = `get_division_leaderboard(Competition div_8d3ead22-…)`, lifetime `mean_round_score`.
- The Competition board lists only players WITH a champion; roster churn (submit/retire) can silently
  clear `is_champion` and drop you off the board — after any roster change, verify and re-POST.

## Measurement discipline

No shipping on a vibe. The only verdict is `harness_core.wilson(wins, n)` with **non-overlapping**
CIs (one verdict function, reused by `league_eval.run_league_ab` and local crux/swap).

- **N>=30 per arm minimum.** Small-n "wins" flip sign (documented n=8 win that was a loss at n=30).
  Never trust a raw mean or point estimate — only the CI comparison.
- **Extend, don't re-roll.** Directionally-interesting results extend in 30–50-episode chunks on the
  **IDENTICAL** config/pool. ~10pp effects (e.g. 13% vs 23%) need ~100–150 episodes/arm to separate.
  Most single-round "we scored lower" observations dissolve under an n>=30 reconstruction —
  reconstruct before declaring a crux.
- **Pool same-direction deficits** across RELATED configs to clear Wilson when no single config
  separates (the configs overlap individually; pooling tightens the CI). This is how the first real
  tier5c deficit was found (Kyle: 21/90 vs 39/90 pooled, each member config overlapping at n=30).
- **A crux is a hypothesis about the CURRENT policy**, not a permanent record. Every policy update
  re-runs ALL open cruxes — the sweep is also the regression guard. Close the ones the update fixed.
- **Refutations are results.** Record every measured negative with numbers so the lever is never
  rebuilt. See `guides/refuted-levers-do-not-rebuild.md` for the banked refuted-lever ledger.

## The two-slot live A/B and promotion

Run exactly **TWO** live policies — champion + one rolling experiment. A third or a stale experiment
dilutes the per-player round mean; the pair is a free live A/B at half data-rate each.

- `coworld submit` qualifies INTO the experiment slot; it does NOT auto-displace the champion. Even a
  candidate that is only **non-inferior** in constructed tests belongs in the experiment slot,
  because the league mix samples configs the top-7 ladder never runs.
- **Promote only when BOTH hold:** (1) **live-ahead** — clean-round mean (collapsed rounds with
  winner-score < 20 filtered out) sustainably beats the champion's, variance-aware (Welch over a WIDE
  window; a 15-round window once misread the incumbent by 4+ points); AND (2) **constructed-test
  dominant** in the seeded crux/ladder A/Bs.
- A **windowed z-gate alone can never fire**: as the experiment starts winning, the league rotates
  rounds toward the leader and the LOSER's in-window sample evaporates. Judge on the totality of
  evidence, not a window test.
- **Live-mix replica arms are mandatory before fielding** (Stage 3): a candidate that passes every
  constructed top-7 A/B can still lose points live (documented −5). Run paired candidate-vs-current
  arms over RANDOM fields — sample 7 distinct live members client-side WITHOUT replacement, fresh
  draw per 30-ep chunk, n>=60/side pooled. The server `{"player":{"random":true}}` fill draws WITH
  replacement (dupes, including your own champion) — fallback only. See skill `run-league-ab-eval`.

## Re-resolve live state every launch — it rots within hours

The league rolls policy versions and standings mid-session, baselines go stale within hours, and the
coworld version itself rolls without notice.

- **Re-fetch `live_members` and validate every pvid right before each launch.** Versions FLIP, not
  just advance (a dead pvid went live again within the hour). Resolve a field **by player NAME** →
  current live pvid, never by a hardcoded version label. Pooling across chunks is valid ONLY when the
  field pvids are IDENTICAL. See skill `resolve-live-roster-and-champion-state`.
- **Treat every verdict as a within-battery paired comparison.** Re-run the incumbent as a same-era
  control on the current field whenever a result looks alarming. A "weak field" baseline (26–29/30 in
  the morning) became 0/30 for the SAME policy later the same day — never compare a new build against
  a baseline measured hours ago. (session-derived, unverified)
- Refresh standings before every comparator batch — a new #1 can surge to the top while you are still
  hunting the morning snapshot. (session-derived, unverified)

## Fail loud — no silent fallbacks, no result caching

- A forced-role `slots` rejection (or any unexpected 4xx) must **FAIL LOUDLY** and surface the
  validator message. The explicitly-rejected anti-pattern: a seed-based fallback that assigns roles
  from the seed and post-filters episodes — that silently changes WHICH ROLE is measured and corrupts
  the A/B with no error. A forced-slots rejection is a designed hard failure, not a condition to
  paper over. The live-acceptance gate on a new coworld version is one real A/B at `--num 2`; if the
  server 400s on `game_config_overrides.slots`, STOP and surface it.
- **Never cache or dedupe results** — the same pairing must be re-runnable many times. A wedged
  participant fails loud, it does not wait forever.

## Keep the loop alive and league actions gated

- **In-flight experience requests are the heartbeat.** If none are in flight and none were created
  recently, the loop is stalled regardless of how healthy the ladder looks — keep probes/extensions
  running and a heartbeat monitor up (count fresh local workdir files as liveness, not just xreqs).
  Background pollers/subagents die silently at session restarts; each lane checkpoints to STATE.md so
  a relay agent resumes losslessly. A client poller crash is NOT a backend failure — re-fetch the
  existing xreq id, never resubmit. See skill `watch-and-monitor-with-poller`. (session-derived,
  unverified)
- **League-visible actions are gated on explicit user approval** and done only by the lead agent,
  never a subagent: submit, retire, champion swap, and any external action (bug filing, anything
  beyond the private optimization Asana project).

## Verify before porting — most rival techniques are already implemented

The most expensive class of wasted work is re-porting a rival move notsus already has. notsus already
implements log-odds suspicion, witnessed-kill/vent confirmation, exact-TSP / clearance-aware A*
routing, isolated-victim + trajectory-intercept + unwitnessed-kill imposter play, the
recruitment-cascade chat, and the LLM advisor — **the crewborg "techniques to port" list is largely
STALE.** Before proposing any port:

- **Measure the existing fire-rate first.** Several "missing" techniques fire 0/anywhere once
  measured (the Tier-1 deduction port did not move crew win rate — crew games are task-decided).
- **Classify the rival behavior before copying** (session-derived, unverified):
  1. **Bundled-cost** — benefit inseparable from a side-effect (a meeting both stops kills and risks
     wrong ejections; you can't take half).
  2. **System-dependent** — payoff depends on a capability you lack (build the prerequisite, e.g.
     task throughput, first).
  3. **Surface-vs-mechanism** — you'd copy the visible action without the internal state that decides
     when to take it.
  A cheap causal probe: ablate the suspected mechanic for both bots via `game_config_overrides`
  (e.g. `buttonCalls: 0`) and re-run paired arms — one n=30/arm ablation proved a rival's entire
  41%-vs-18% edge was a single button press.
- For the bot's architecture and what is already implemented, see
  `guides/notsus-bot-architecture.md` before proposing a port. The open crew levers that remain after
  all the refutations are in `guides/crew-strategy-and-open-levers.md`.
