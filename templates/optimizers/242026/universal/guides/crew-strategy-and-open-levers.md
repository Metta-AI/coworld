# Crew strategy and the open levers

Reference for anyone working on the crew side of a crewrift policy. It states the
win-model the crew plays under, then walks the levers that are still open, the ones
that are exhausted, and where the remaining effort actually has expected value.

Read this before proposing a "make crew win more" change. Most of the obvious ideas
have already been measured; this note tells you which are alive and which are dead, with
the numbers.

Code citations (`file:line`) come from session notes against crewrift `0.1.36` /
branch `daveey/llm-advisor-0136`. They were accurate at capture but are point-in-time —
re-grep before relying on a specific line number.

---

## 1. The win-model

A crewrift game is a three-way race. The crew wins if **either** branch completes
before the imposters reach parity:

- **Task win** — `allTasksDone()`: every mandatory assigned task is completed.
- **Vote win** — the crew ejects all imposters via meetings.
- **Imposter win** — imposters reach **parity**: `aliveImposters >= aliveCrewmates`
  (`sim.nim:3333`). Parity is reached by kills **or** by wrongful vote-ejections of
  crew. It is *not* "4 kills" — every crew you lose, to a knife or to a bad vote, counts
  the same toward parity.
- **Timeout** — `maxTicks` is a no-`+100` draw; `finishGame` early-returns on
  `timeLimitReached` (`sim.nim:2258`). A timeout is not a win.

Two facts drive everything below:

1. **Dead crew become ghosts that still complete their assigned tasks.** A killed or
   ejected crewmate becomes a ghost that keeps `role == Crewmate`, keeps receiving its
   task arrows (`global.nim:2194` gates only on role), and still runs the task-completion
   block — `applyGhostMovement` (`sim.nim:2744`) reaches `completeTask` (`sim.nim:2792`)
   with **no `alive` check**. notsus already exploits this: a ghost navigates to
   `nearestTaskGoal` and completes tasks (`notsus.nim:5166`). So `totalTasksRemaining`
   counts dead crew's tasks (`sim.nim:3245`), but ghosts can still finish them — and a
   killed crewmate is converted into an **unkillable, unvotable task-completer**, which
   *accelerates* the task win rather than blocking it. The task win is reachable despite
   deaths. (This corrects an older note that claimed task wins were near-impossible; that
   note missed ghost tasking.)

2. **Crew games on strong fields are decided by tasks, not by deduction.** On the
   league's evasive maps kills are isolated by design and the vote path has little
   leverage in most crew games. That is why the deduction ports below mostly didn't move
   crew win rate.

The practical reading: **task throughput is the primary crew lever; vote-conversion is a
secondary lever that only matters on vote-decided fields; positioning/presence is not a
lever at all.** The rest of this note is that claim, with evidence.

---

## 2. Where the gap actually is (near-optimal, broad, marginal)

Per-episode decomposition of daveey's champion (`tier4`) against the leaders, aggregated
over ~400–800 episodes/policy across 4 Competition rounds (`list_episode_requests(round_id=...)`
→ per-ereq `participants` + `scores`):

| policy | mean/ep | win% (≥80) | mid% | shutout% (≤5) |
|---|---|---|---|---|
| crewborg-optimizer-what | 52.7 | 46 | 46 | 9 |
| **truecrew (#1)** | 50.8 | 43 | 48 | 9 |
| **daveey-notsus-tier4** | 46.3 | 40 | 48 | **11** |

**The gap is broad and marginal, not a specific exploitable hole.** tier4 trails truecrew
by ~4.5/episode, split as ~3% fewer wins (40 vs 43) plus ~2% more shutouts (11 vs 9). The
bot is a strong all-rounder near the top, not structurally broken — porting crewborg's
full public playbook plus an Opus advisor got it here. Closing a broad few-percent gap to
a **private** bot needs general superiority, not one fix.

Method caveat: role (crew vs imposter) is **not** in the episode data, so these wins and
shutouts are not split by role. The aggregation method is reusable for future gap analysis.

**First validated lever against this broad gap: clearance-aware A\*.** notsus's A\* hugged
walls and corners (uniform step cost) → momentum snags → wasted ticks. A soft
wall-clearance penalty (a cell with a wall within ~7px costs +1; cost not constraint,
heuristic stays admissible, no path failures) shipped as `daveey-notsus-nav`. Crew A/B in
the reliable seat: `daveey-notsus-nav` 29/30 vs `tier4` 26/30, crew score 104.6 vs 94.6 —
did not regress, positive point estimate (CI overlaps). This was the first measured crew
gain against the broad gap.

Note: predictive-stop / momentum braking (crewborg's other Tier-3 nav element) is
**already** in notsus (`coastDistance` / `shouldCoast` — coasts when momentum will carry
it to the target). Do not re-port it. Remaining nav ideas are only marginal parameter
tuning (ClearanceProbe / WallClearancePenalty), which chases the inconclusive CI — low EV.

With clearance-A\* plus the existing capabilities, **all of crewborg's public Tier-1/2/3
levers are covered.** The path beyond is original research against the private #1.

---

## 3. Open lever — task routing (TSP over greedy), the contested-band one

This is the live crew-win lever. Both alive and ghost task selection in notsus was
**greedy nearest-task** (`nearestTaskGoal`, "closest known active task station",
`notsus.nim:4624`). The bot already knows all task locations and which are its own (labeled
task arrows / bubbles), so it can plan a route instead of greedily hopping.

**MEASURED (session-derived, unverified):** replacing greedy with an exact open-tour
Held-Karp route over the remaining mandatory tasks — same Manhattan metric, same candidate
predicate, only the **visit order** changes; a 1.5x first-leg detour cap for living crew as
an isolation guard, uncapped for ghosts — is a real crew win **in the contested regime**:

> n=48, `kill_cooldown=750`, strong LLM imposter opponents: route **46/48** (0.958, CI
> 0.860–0.988) vs greedy **36/48** (0.750, CI 0.612–0.851). CIs separated. Mean crew score
> 82.7 → 103.7 (~+21pp win rate).

Two caveats that decide whether you can even see the effect:

- **Ceiling regimes hide it completely.** At league-default kill cooldown (900) or vs weak
  imposters, both arms win ~90–100% and the change is invisible (6/6 vs 6/6 identical mean;
  45/48 vs 43/48 inconclusive). A small-n harsh regime (`killCooldown=200`, n=8) even showed
  a noise-level *negative* direction.
- **The router already shipped into notsus** (later sessions found it present and
  near-optimal — "routing already exact-TSP" was a closed lane). So the block above is the
  provenance / measurement record for it, **not** an open idea to re-implement.

**The reusable, durable rule here — this is the part to carry forward:** *when evaluating
any crew task-throughput change, pick an eval regime where crew win rate sits in the
~0.4–0.7 band first, or the change cannot register.* Saturated evals are why the routing
gain was nearly missed. This is the single most important methodology fact for crew work.

Implementation note: `nearestTaskGoal` had exactly one caller, so the wire-in was a
one-line change returning the identical tuple.

### Ghost routing — the zero-risk sub-case (still open in spirit)

Ghosts fly straight, ignore walls, can't die, and have no isolation tradeoff. So **ghost
routing is the zero-risk lever**: uncapped TSP for ghosts has no downside (no isolation
deaths to trade against), and a killed crewmate becoming an unkillable task-completer is
pure upside toward `allTasksDone`. Alive routing trades off against isolation deaths (the
1.5x first-leg cap is the guard); ghost routing does not. If you revisit routing, the ghost
path is where marginal gains carry no risk.

Whether routing moves overall win rate depends on **how often `allTasksDone` is the
deciding outcome** — instrument a batch that logs the win path per episode
(eject / task / parity / timeout) before and after any routing change.

---

## 4. Open lever — vote-conversion (ejecting imposters), on vote-decided fields

Crew games on the strong evasive fields are mostly task-decided, so the vote path has
limited leverage there (see §1, fact 2). **But on vote-decided fields — fields where
imposters get ejected and that decides games — vote-conversion is the specific hole.** The
~2% excess shutout rate in §2 is partly the failure to convert evidence into ejections.

A "never votes" defect does **not** decompose into one threshold fix. It is a three-stage
ladder, and only the last stage converts to wins (session-derived, unverified; measured at
the truecrew crew-seat crux, seed 4242, n=30/arm/stage):

1. **Reachable gate** (`tier5a`) — lower the suspicion threshold so it is *mathematically
   attainable* from the bot's real evidence terms. **Audit the arithmetic before tuning
   anything:** notsus's crew gate required P(imposter) ≥ 0.8 (~1.39 log-odds) while its only
   crew evidence cues maxed at 1.28 log-odds — the gate could **literally never fire** (0
   votes in 30 episodes). Lowering it alone changed almost nothing → **3/30** (evidence
   rarely accrues, so a reachable-but-unfed gate still doesn't fire).
2. **Pile-on voting** (`tier5b`) — join existing vote majorities. This matched the rival's
   vote *rate* but not its wins → **8/30**. A lone correct vote doesn't cascade into an
   ejection.
3. **Recruitment cascade** (`tier5c`) — a once-per-meeting "`<color> sus`" chat line (the
   exact format every field parser reads) **plus** joining a single existing vote only when
   own suspicion corroborates the target (so a rival's frame-job can't pull you). This was
   the breakthrough → **13/30** at the crux, beating the donor bot's own **11/30** in the
   same seat. `tier5c` passed the imposter and weak-field regression gates and was promoted
   to champion.

The ladder: `tier4` 2/30 → `tier5a` 3/30 → `tier5b` 8/30 → `tier5c` 13/30 (vs truecrew
11/30). The missing piece in stages 1–2 was never the bot's own vote — it was the **social
cascade** (recruiting other voters).

**Reusable rules:** any time a vote/meeting mechanism "never fires," check threshold
*reachability* against the actual evidence ceiling first. Any time a vote fix doesn't
convert to wins, ask whether the missing piece is the cascade (recruiting voters), not your
own ballot. The corroboration condition is load-bearing — pile-on without it makes the bot
exploitable by enemy frame-jobs.

---

## 5. The only remaining lever vs the private #1 — mining truecrew's replays (scoped, not built)

After all of crewborg's public playbook plus clearance routing, daveey sits at ~crewborg's
tier (#4–6). The #1 is **truecrew (Andre von Houck, ~54.6), whose source is private.** The
only concrete path to its edge is mining its **replays** — behavior is observable even
though source isn't.

**Feasibility CONFIRMED:**

- Every league episode has a `replay_url` on its `episode_request`
  (`list_episode_requests(round_id=...)` → `er.replay_url`; `er.participants` gives
  position→policy_name; truecrew is one slot).
- The URL is a **public S3 object**
  (`https://softmax-public.s3.amazonaws.com/replays/<uuid>.json.z`), plain GET, no auth,
  ~70KB zlib-compressed.
- Despite the `.json.z` name it decompresses to **binary** (bitworld replay codec, not
  UTF-8 JSON — `json.loads` fails). Parse with the Nim codec: `src/crewrift/replays.nim`
  `parseReplayBytes*(bytes)` / `loadReplay*(path)` → `ReplayData`; `ReplayPlayer`
  reconstructs per-tick sim state (positions, kills, tasks, votes, events).

**BLOCKED — replay non-determinism (sim version mismatch).** A Nim extractor
(`src/crewrift/replay_mine.nim`: `uncompress` → `parseReplayBytes` → `defaultGameConfig()`
+ `update(data.configJson)` → `initSimServer` → loop `stepReplay`) compiles and runs but
prints **"Replay hash mismatch at tick 93"**. Replays store only **inputs + periodic
hashes**, so reconstruction re-runs the sim — and the local `_crewrift-0136` sim diverges
from the league's recording version (`cow_446e69c8`) after ~93 ticks. Reconstructed
positions/tasks/kills past tick 93 are a **different simulation**, not truecrew's real play.

**Input-only analysis DONE — no portable edge found.** Integrating per-player held-button
durations from `data.inputs` (determinism-proof, no sim) showed truecrew is one of the
*least* input-active bots: 10 A-presses, 51% idle, while #2 (Aaron's Optimizer) spams 603.
A-press cadence ranges 3–633 across the field with **no correlation to rank**. Conclusion:
truecrew's edge is **decision quality** (targeting / positioning / timing), not input-level
activity — input mining cannot reach it.

**To unblock (two options):**

1. **Version-matched reconstruction** — obtain/build the exact `cow_446e69c8` crewrift sim
   (try `coworld download crewrift`?), link `replay_mine` against **that**, so the hashes
   match. Then do positional / decision analysis: where truecrew is at kills, how it routes,
   when it votes. This is the realistic remaining path to #1.
2. Watching rendered replays manually — non-portable, doesn't scale.

In-session input mining is exhausted; the open work is the version-matched sim. Minor known
bug in the scratch tool: `n`/`ensure` locks player count to 1 during the lobby — set `n`
only once `game started` / players==8 (does **not** fix divergence). `replay_mine.nim` plus
its binary are **untracked scratch** in `src/crewrift/` — do not bundle into bot commits.

---

## 6. Refuted levers — do NOT rebuild these

Each verdict below is backed by a measurement. If you find yourself proposing one of these,
stop: it was tried and it did not work.

### ⛔ DO NOT build presence / positioning / anti-isolation as a crew lever
**MEASURED (120 eps):** crew presence/positioning is **not** a lever. We already
*out-cluster* league #1 (31.4% vs 28.6% within 80px); **no bot witnesses kills** (kills are
isolated by design); and clustering↔win is **reverse causation** (early-window 20% vs 17%).
Do not build a presence / group-adjacent-ordering / anti-isolation tier.

### ⛔ DO NOT build a proactive-meeting / extra-vote crew lever
**MEASURED:** the game ends at imposter parity (4 of 6 crew removed by kills **or**
vote-ejections), not "4 kills". The proactive-meeting lever cuts kills but the meeting's
vote ejects innocents → **ejection-parity loss**. sussyboi cuts 4-kill losses 68→5 but pays
**48 ejection losses**. Adding a vote to suppress kills trades a kill-parity loss for an
ejection-parity loss — net negative. (The next kill-suppression idea, if any, must work via
survival/positioning **without** adding a vote.)

### ⛔ DO NOT re-port crewborg deduction to raise crew win rate (Tier-1 deduction)
**MEASURED:** the Tier-1 deduction port did **not** improve crew win rate (27/30 vs 29/30).
Crew games are task-decided (kills=0 in most), so the vote path has no leverage. The crew
gain is task throughput/routing, not deduction. (Distinct from §4: §4's vote-conversion
gain is on *vote-decided* fields; broad-field deduction porting is refuted.)

### ⛔ DO NOT re-port track-memory / follow-to-death victim-link perception
**MEASURED:** porting crewborg's track-memory follow-to-death victim link into notsus fires
**0/anywhere** (witnessed-victim-link 0/30; pooled crux 23/120 vs tier5c 20/120, overlap,
no regression). The deduction/track-memory lane (tier8b/8c/9) is closed. The reason it can't
fire: notsus is within 120px of only **4/19 kills** — the failure is **presence/positioning
at kills, not perception fidelity** (robust viewport recall ≈0.77, frame-drops ~0, crewborg
reads the same wire protocol — no data ceiling). A recall/track-memory fix cannot see kills
the bot isn't near. (One bounded in-scope perception bug remains: `protocolSelfObject` 12px
self-drop, ~22% of recall misses — that's a real bug, not a lever.)

### ⛔ DO NOT re-port predictive-stop / momentum braking nav
**Already implemented** in notsus (`coastDistance` / `shouldCoast`). Re-porting it is
duplicate work (see §2).

---

## 7. Where to spend effort next — the priority order

Tying the win-model to where the EV is:

1. **Task throughput on contested fields** is the primary crew lever, because most crew
   games are task-decided and ghosts keep completing tasks after death. Routing is the
   proven instance; the ghost-routing sub-case is zero-risk. **Always eval in the ~0.4–0.7
   crew-win band** or the change is invisible.
2. **Vote-conversion (the recruitment cascade)** is the secondary lever, and only on
   vote-decided fields — it closes part of the excess-shutout gap there. Reachable gate →
   pile-on → corroborated recruitment cascade; only the cascade converts.
3. **Version-matched truecrew replay reconstruction** is the only concrete path past the
   private #1, but it is gated on getting the `cow_446e69c8` sim so reconstruction hashes
   match. High ceiling, blocked, scoped-not-built.
4. **Everything in §6 is dead.** Presence, proactive-meeting/extra-vote, broad-field
   deduction porting, track-memory perception, and re-porting coast nav are all refuted or
   redundant — do not spend effort there.

The strategic frontier in one line: **the bot is near-optimal and broadly behind a private
#1 by a few percent; the only proven crew gains are task-routing in a non-saturated regime
and vote-conversion on vote-decided fields, and the only path to the #1 is replay
reconstruction nobody has unblocked yet.**

---

### Source provenance

Synthesized from five sources. `(session-derived, unverified)` content is the TSP-routing
measurement (§3) and the vote-ladder measurement (§4) — both flagged inline; everyone else
is from reviewed memory notes.

- `crewrift-ghosts-complete-tasks` (memory) — §1 ghost mechanics, §3 ghost routing.
- `tsp-task-routing-beats-greedy-under-pressure` (session) — §3 routing measurement + the
  0.4–0.7 eval-band rule.
- `crewrift-leaderboard-gap-diagnosis` (memory) — §2 per-episode gap, clearance-A\*.
- `crewrift-truecrew-replay-mining` (memory) — §5 replay mining.
- `vote-fix-ladder-gate-pileon-recruitment` (session) — §4 vote ladder.

Refuted-lever verdicts in §6 are cross-referenced from the project memory index
(`crewrift-presence-lever-refuted`, `crewrift-parity-win-model`,
`crewrift-tier1-deduction-result`, `crewrift-tier9-perception-port-result`,
`crewrift-perception-presence-not-recall`).
