---
name: diagnose-llm-advisor-health
description: >-
  Confirm an LLM advisor (e.g. the notsus Bedrock vote advisor) is actually firing before
  trusting any result that depends on it. Load this when an LLM-advised bot behaves identically
  to its heuristic baseline (notably: votes SKIP every meeting / ejects zero imposters), or
  before/while running ANY advisor-sensitive A/B or high-concurrency eval. The advisor fails
  silently — results.json looks clean while the bot is a pure skip-bot — so verify the advisor
  health signature first, otherwise the A/B measures nothing.
---

# Diagnose LLM advisor health

The notsus crew bot calls an out-of-process LLM advisor (`advisor.py`, a Bedrock Claude call) on
every meeting to decide its vote. On ANY failure the advisor exits non-zero and the Nim bot falls
back to a scripted heuristic floor — so a dead advisor produces a bot that is byte-for-byte a
heuristic skip-bot, and every A/B run over it measures **nothing**. This recipe confirms the
advisor is actually firing before you trust an advisor-sensitive result.

The advisor (`/Users/daveey/packages/crewrift-player-optimization/universal/tools/advisor.py`):
- Reads a meeting snapshot as JSON on **stdin**, prints one line `{"vote": "<color or skip>", "chat": "..."}` on **stdout**.
- Calls Bedrock model `us.anthropic.claude-opus-4-7` by default, overridable via the env var `CREWRIFT_BEDROCK_MODEL` (and region via `AWS_REGION` / `AWS_DEFAULT_REGION`, default `us-east-1`).
- On any exception (no creds, gated model, throttling, contention) it writes `advisor error: <exc>` to **stderr** and `sys.exit(1)`. The Nim side then logs the failure and uses its heuristic vote floor.
- Retry config is bounded to stay inside the vote deadline: `max_attempts=4`, `read_timeout=5s`, `connect_timeout=2s` — sized so retried calls land within `LLMVoteDeadlineTicks=150` (≈ 6.25s @ 24fps).

## The one signature that matters

`vote_timeouts=0` in `results.json` proves **NOTHING** — it was 0 even when the advisor was 100% broken. **(session-derived, unverified)** The real signature lives ONLY in the per-agent (policy_agent) logs. Grep them for the decision strings:

| Log string | Meaning |
| --- | --- |
| `llm advisor invalid -> skip` | Advisor process **errored** — no creds, gated model, or CPU contention. A bot whose every meeting logs this is a silent pure skip-bot. **This is the failure to hunt.** |
| `llm timeout -> ...` | Latency exceeded the deadline (heuristic fallback fired). |
| `llm advisor vote <color>` / `llm advisor: skip` | A **real LLM decision**. `skip` with zero errors IS success when there was genuinely no lead. |

A bot logging `invalid -> skip` on every meeting is broken even though `results.json`, `wins`, and `vote_timeouts` all look healthy. **(session-derived, unverified)**

## Recipe

### Step 0 — Decide what you're actually testing
If your A/B candidate or baseline depends on the advisor (vote-conversion, deduction, any
meeting-path change), the verdict is only meaningful if the advisor fires for the arm that
needs it. If you cannot confirm firing, do not report the verdict. Per the loop's
"don't fire blind" rule: a result you cannot reproduce or attribute to the lever is wasted
spend — fix the advisor health first, then run the A/B.

### Step 1 — Probe the advisor binary directly (creds + model gating)
Run the advisor by hand with a tiny snapshot. This isolates the **model/credentials** layer from
in-game contention. From a shell with the same AWS identity the eval runs under:

```bash
echo '{"my_role":"crewmate","my_color":"pink","options":["pink","red","skip"],"players":[],"dead":[],"chat":[],"votes":{}}' \
  | CREWRIFT_BEDROCK_MODEL=us.anthropic.claude-opus-4-7 \
    python /Users/daveey/packages/crewrift-player-optimization/universal/tools/advisor.py ; echo "exit=$?"
```

Outcomes:
- Prints `{"vote": "...", "chat": "..."}` and `exit=0` → the model is invokable with these creds. Good.
- `advisor error: ...AccessDenied...` and `exit=1` → the model is **gated for this account/role**. The creds path is fine; only the model is disabled. This has killed the advisor fleet-wide: the configured default model was simply not enabled in the execution account. **(session-derived, unverified)** Fix by enabling the model OR swapping to an enabled one via the `CREWRIFT_BEDROCK_MODEL` env — **no image rebuild needed**, it can be injected as a secret-env override. Check for that env path before rebuilding.
- `advisor error: ...NoCredentials.../...could not be found...` → wrong/absent AWS identity. Fix creds, not policy logic.

Equivalent in-fleet check (verify the EXACT model id is invokable from the EXACT execution
account/role, e.g. via an SSM `invoke-model` probe against the running containers' identity). A
clean `AccessDenied` there confirms gating fleet-wide. **(session-derived, unverified)**

### Step 2 — Reproduce at the eval's real concurrency (not a synthetic burst)
CPU contention destroys the advisor, and it does NOT show up in burst probes:
- Same image/config/box: **0.5% invalid at 2 concurrent games** vs **100% invalid (208/208 calls) at 16 concurrent games** (~128 containers on 32 vCPU). An earlier datapoint: 84% invalid at 8×8 concurrency. **(session-derived, unverified)**
- Synthetic bursts of 24/40/96 concurrent advisor calls all **succeeded** while in-game calls failed 84% under full load — the mechanism is **sustained multi-container contention during live realtime games**, which a burst does not reproduce. **(session-derived, unverified)**

So: do NOT validate the advisor with a one-off burst or a 2-game smoke and then run a 16-wide
A/B. Compare the **same workload at the concurrency the A/B will actually use**. If the A/B is
high per-box concurrency, an `invalid->skip` rate there means you are measuring **load damage,
not bot logic** — lower per-box concurrency (more boxes, fewer containers each) or accept that
the verdict is contaminated.

### Step 3 — Force the advisor to actually run in a smoke
A smoke that never has a meeting validates nothing — crew can finish all tasks before any kill,
so the advisor never executes. Force bodies/meetings by lowering kill cooldown so the deduction
path is exercised. **(session-derived, unverified)** Then grep the per-agent logs for the Step-1
table strings. `llm advisor: skip` with zero `invalid`/`error` lines IS success when there was no
real signal — the point is to see a **real LLM decision string**, not necessarily a vote.

### Step 4 — Grep the run's per-agent logs for the signature
After the smoke or the A/B, pull the policy_agent logs for the advisor arm and count decision strings:

```bash
# adjust the path to wherever the run's policy_agent stdout/stderr landed
grep -ohE 'llm advisor (invalid -> skip|vote [a-z]+|: skip)|llm timeout' <agent_log_path> | sort | uniq -c
```

Healthy advisor: a nonzero count of `llm advisor vote <color>` / `llm advisor: skip` and a near-zero
count of `invalid -> skip`. Broken advisor: `invalid -> skip` dominates (or is 100%).

### Step 5 — Only now trust the A/B
The A/B engine is
`/Users/daveey/packages/crewrift-player-optimization/universal/tools/eval.py` (CLI front door) →
`league_eval.run_league_ab` (runs candidate & baseline as concurrent server-side Observatory
experience requests, league top-7 fill the field). For background/dashboard runs it's wrapped by
`episode_runner.py`. None of these surface advisor health — they only report `wins`, Wilson CIs,
score, kills, `vote_timeouts`. Treat their verdict as valid **only after** Steps 1–4 confirm the
advisor fired for the arm under test.

To get ground truth on what actually happened in a game (did an imposter get ejected? was the bot
even present at the kill?), decode the S3 replay with
`/Users/daveey/packages/crewrift-player-optimization/universal/tools/replay_mine.nim` — the
authoritative per-slot `slot,role,reward,tasks,alive,diedTick,dist` oracle. A bot that logs real
`vote <color>` lines but still ejects 0 imposters is a *different* defect (presence/suspicion,
not advisor health) — see the vote-conversion memory note.

## Gotchas

- **`vote_timeouts=0` is not health.** It stays 0 while the advisor is 100% broken. Only the per-agent decision strings tell the truth. **(session-derived, unverified)**
- **Burst probes lie.** They pass while live high-concurrency games fail. Reproduce at the eval's real in-game concurrency. **(session-derived, unverified)**
- **Model gating ≠ bad creds.** A clean `AccessDenied` means the creds are fine and only the model is disabled for the account — swap via `CREWRIFT_BEDROCK_MODEL` env, no rebuild. **(session-derived, unverified)**
- **A meetingless smoke validates nothing.** Force bodies (low kill cooldown) or the advisor never runs and you "confirm" nothing. **(session-derived, unverified)**
- **Timing tuning has a hidden cost.** Do NOT raise `LLMVoteDeadlineTicks` to chase advisor fire-rate. Going 150 → 200 took fire-rate 76% → 100% but cut the vote-cast margin (~90 ticks → ~40), doubling crew vote-timeouts (~0.5 → ~1.0/game, −10 score each) and net-regressing — the regression only surfaced 3 days later in a dashboard run. **150 is the verified-good value** (~90-tick cast margin; slow advisor calls fall back to a body-suspect vote that still lands). Any meeting/advisor timing change must be checked against **vote-timeout counts per game**, not just advisor fire-rate. **(session-derived, unverified)**
- **Don't fire blind controlled rounds off a flaky local result.** If a local advisor A/B is non-deterministic / won't reproduce, a hosted round won't disambiguate it either. Fix the variance (often: advisor health or concurrency) before spending hosted rounds. **(session-derived, unverified)**

## Success check

You are done when, for the arm whose result depends on the advisor:
1. Step 1's direct probe prints `{"vote": ...}` with `exit=0` (model invokable from the eval's account/role), AND
2. The run's per-agent logs show a nonzero count of real decision strings (`llm advisor vote <color>` or `llm advisor: skip`) with `invalid -> skip` near zero, AND
3. That count was produced at the **same concurrency** the A/B uses (not a burst or a 2-game smoke).

If `invalid -> skip` dominates, the advisor is dead/contended — the bot is running on its heuristic floor and any advisor-sensitive verdict is meaningless. Fix the model gating / creds / concurrency before reporting anything.
