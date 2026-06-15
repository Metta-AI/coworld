# The Working Loop: Optimizing the notsus Bot for the Crewrift Coworld

Reconstructed from agent sessions spanning ~2026-06-05 to 2026-06-12. This is the loop as it
actually ran — including the failure-handling sub-loops and the human's recurring steers — written
so a fresh agent can execute it. Anything inferred rather than directly observed is marked
(inferred).

## Cycle shape

```
        ┌──────────────────────────────────────────────────────────────────┐
        │                                                                  │
        ▼                                                                  │
 [0] ORIENT ──► [1] PICK LEVER ──► [2] ROOT-CAUSE ──► [3] EDIT NIM BOT     │
 (refresh        (crux from          (source + logs     (worktree, nim     │
  league state,   standings/replays/  + replay decode    check ladder)     │
  memory, git     rival mining/       BEFORE coding)          │            │
  status)         user observation)                           ▼            │
        ▲                                            [4] BUILD amd64 +     │
        │                                                UPLOAD POLICY     │
        │                                                     │            │
   [9] RECORD ◄── [8] SHIP or REFUTE ◄── [7] EXPLAIN ◄── [5/6] SERVER-SIDE │
   (memory note,   (validation ladder,    (replay_mine,    A/B  N>=30,     │
    Asana story,    submit, champion       policy logs,    Wilson verdict ─┘
    docs commit —   mgmt, live A/B         config-ablation
    refutations     with cut rule)         probes)
    too)
```

One full cycle (edit → build → upload → N=30/arm server A/B → verdict) takes roughly 30–60 min
wall-clock; the floor is realtime sim pacing (~maxticks/24 seconds per episode) plus ~2 min
episode provisioning. Run multiple cycles in parallel — the server is not the bottleneck.

## Ground rules (the human enforced these repeatedly)

- **Never ship on a vibe.** Every behavioral claim needs an A/B at N>=30 per arm with Wilson CIs;
  treat overlapping CIs as INCONCLUSIVE, never as a win. Extend directionally-interesting results
  in 30–50-episode chunks on the IDENTICAL config and pool; 13%-vs-23% effects need ~100–150/arm.
- **Refutations are results.** Record measured negative results with numbers (Asana story +
  memory note) so the lever is never rebuilt. This campaign banked ~10 refutations against 2–3
  shipped wins; that ratio is normal.
- **If no experience requests are in flight, the loop is stalled** — standing user rule. Keep
  probes or extensions running at all times; run a heartbeat monitor that alarms on sustained
  quiet (but count fresh local files as liveness too, since build/analysis phases make no
  requests).
- **Don't idle on pollers.** When early sweep points already bound the answer, fire the next
  experiment at the estimated optimum in parallel instead of waiting for stragglers ("what are
  you waiting for" was a real steer).
- **League-visible actions (submit, retire, champion swap, external bug filing) are gated on
  explicit user approval** and are done only by the lead agent, never by subagents. A subagent
  once submitted a policy in breach of this and it went unnoticed for a day because monitoring
  filtered by name substring — audit the FULL membership roster, not filtered views.
- **Fail loud.** No fallbacks that silently change what is measured ("dont fallback, fail if
  rejected"). No result caching/dedupe — the same pairing must be re-runnable many times.

---

## Step 0 — Orient (start of every session)

Run these before trusting anything local:

1. `uv run coworld leagues <league_id>` — compare the live coworld ID against what local
   manifests/harness reference. The league rolls game versions without notice (0.1.24 → 0.1.36
   happened mid-campaign); if it rolled, do a fresh `coworld download crewrift`, run one baseline
   episode, and diff the scoring constants (`git show <ref>:src/crewrift/sim.nim | grep` for
   TaskReward/KillReward/WinReward/VoteTimeoutPenalty) before trusting any prior numbers.
2. Read the project memory index (`~/.claude/projects/-Users-daveey-code-crewrift/memory/MEMORY.md`)
   and the repo playbook (`_harness/CREWRIFT_PLAYBOOK.md`) plus the process docs
   (`docs/optimize-policy.md`, `docs/league-api.md`). Memory notes supersede stale playbook
   sections. Check the playbook's regression list before re-implementing anything (witness-aware
   kill, cursor persistence, etc. are recorded regressions).
3. `git status` / `git diff` the bot repo. The bot source lives in a **separate nested git repo**
   — `_crewrift-0136/players/notsus/notsus.nim` plus `advisor.py` (clone of
   Metta-AI/coworld-crewrift, default branch `master`, working branch `daveey/llm-advisor-0136`)
   — inside the `daveey/crewrift` harness repo, whose .gitignore excludes all policy source.
   Prior sessions leave uncommitted edits; a dirty tree once silently bundled an imposter rewrite
   into a "crew-only" build and invalidated an A/B conclusion. Know exactly what each image will
   be built from.
4. Pull current standings via `get_division_leaderboard` (the official ranking — a slow cumulative
   per-user lifetime mean). Do NOT judge by ad-hoc per-policy round aggregations, and remember:
   "champion" means the user's leaderboard-scoring player slot, not winner. Each user has two
   player slots (champion + experiment).
5. Check the league for already-completed runs of the pairing you care about before launching new
   ones — fresh artifacts from a prior session are free episodes to mine.
6. After any restart, audit background state: re-list agent workdirs by newest file timestamps,
   read each lane's STATE.md, stop duplicate monitors, and respawn dead lanes (background agents
   do not survive session restarts).

## Step 1 — Pick the lever (crux generation)

A "crux" is a confirmed, reproducible per-seat deficit: a complete experience-request body
(pinned `seed` in game_config_overrides + forced imposter slots + seat-ordered roster) stored
verbatim in a tracking task so anyone can re-spin the exact situation. Sources of cruxes, in the
order they actually paid off:

- **Standings deltas**: which live players beat you, by how much, over a wide round window. Re-rank
  before every comparator batch — the board churns within hours (a new #1 surged unseen twice).
- **Round reconstruction**: every "we scored lower" league round needs an n>=30 reconstruction
  before becoming a crux. Most dissolve as variance — single rounds are a few episodes of
  role/seat/draw noise.
- **Swap tournaments on your own low-score episodes**: for your own past experience-request
  episodes you hold the exact seed+config. Rerun that precise setting with each top player swapped
  into your seat (requester-less all-opponent rosters). Either someone separates above you
  (confirmed crux with a who-does-better table) or nobody does (record "hard map, not a crux").
- **Counterfactual "their bot in our seat"**: arm A = your policy as requester in seat k; arm B =
  the rival's live policy_version_id in the same seat via a requester-less roster. Competitor
  images are private ECR — this server-side swap is the only faithful comparison.
- **Rival mining**: read public rival source (crewborg in Metta-AI/players via `gh api`); pull
  team-readable per-tick sqlite trace artifacts (crewborg's trace.db) and rival policy logs from
  the B-arms of your own requests; decode replays (Step 7).
- **The user's own replay watching** — several levers (button-camping, button cooldown
  assumptions) came from the human watching games. Take these as hypotheses, then measure.

Maintain loop state in one private Asana project ("Crewrift Policy Optimization") with two
sections: Crux Games and Improvement Ideas. Crux tasks carry the verbatim reproduction config;
idea tasks are dependency-linked to cruxes; every measured result — including refutations — goes
in as a task story with numbers; close tasks only on validated/refuted-with-evidence. (Asana MCP
quirks: plain-text notes not html_notes; create sections via REST POST /projects/{gid}/sections;
create_task accepts section_id.)

**On every policy update, re-run ALL open crux configs** (user directive): still-failing cruxes
are the regression guard; a crux the new policy passes gets closed as fixed-by-side-effect with
numbers. Cruxes are hypotheses about the *current* policy, not permanent facts.

## Step 2 — Root-cause before implementing

Do not code from the hypothesis. First:

- Read the actual game source in the local clone — `sim.nim` (win conditions, mechanics like
  buttonCalls and kill cooldown), `server.nim` (input path), `global.nim` (sprite emission) — and
  the bot's own decision path in `notsus.nim`, using `rg` + targeted Read with line offsets
  (the file is ~6000 lines; never read it whole).
- **Check what the bot already implements** before porting a technique — notsus already had
  momentum braking and an exact Held-Karp TSP router when those ports were planned.
- **Check whether a trigger is arithmetically reachable**: the signature win of the campaign was
  noticing the crew vote gate required log-odds the evidence terms could never sum to (zero votes
  in 30 episodes). When a behavior never fires, audit the trigger's math against the maximum
  attainable evidence before tuning anything.
- Verify mechanics empirically when source reading is ambiguous — a source-derived conclusion
  ("task win is impossible after a kill") was wrong because a second code path (ghost task
  completion) existed. When the human pushes back on a source-derived claim, re-trace before
  defending; if a wrong finding hit memory, delete the note the same turn.
- Confirm the metric can move at all (see Step 6's instrument-calibration sub-loop) and check
  the advisor/LLM path is actually alive before attributing behavior to logic (Step 7).

When a copied rival behavior fails, descend the causal stack one layer and re-measure rather than
re-tuning the same layer. This campaign descended: vote gate (fixed) → vote conversion → meeting
timing → suspicion model → trajectory memory → sprite recall → presence. Also classify any
port idea up front: is the payoff bundled with a side-effect you can't take half of? Does it
depend on a capability you lack (build the prerequisite first)? Are you copying the visible
action without the internal state that decides it?

## Step 3 — Edit the Nim bot

- One variant = one branch (or one git worktree, e.g. `_crewrift-tier6e`) and one commit, so each
  built image maps to exactly one diff. Name variants in a ladder (tier5a/5b/5c...) and validate
  each dial separately so contributions are measured, not guessed.
- Validation ladder, cheapest rung gates the next:
  1. `nimby --global sync` if deps complain (deps come from nimby.lock, not nimble).
  2. `nim check -d:botHeadless -d:useMalloc --hints:off players/notsus/notsus.nim` from the bot
     repo root — full semantic analysis in seconds, with the same defines the Dockerfile uses.
     (`-d:botHeadless` matters: GUI-only code paths hide dead references otherwise. A pre-existing
     unused `pixelfonts` import warning is expected noise.)
  3. Optional native `nim c -d:release` / native arm64 image build as a fast compile gate before
     paying the emulated amd64 build.
- For deletions: `rg` every identifier of the removed feature, read each touchpoint, and check
  whether helpers are shared before deleting them (buttonGoal looked feature-specific but was a
  shared fallback). Re-grep for zero dangling references after.
- Baseline construction: the A/B baseline must be the same tree minus only the change — build the
  candidate, then `git stash` (or revert-in-place with a /tmp backup), build the baseline with
  identical flags/platform, restore. Confirm the two image IDs differ. Never reuse a days-old
  image as baseline.
- New decision mechanisms must emit trace/telemetry events (the bot uploads an events.jsonl
  player artifact) or the next crux analysis can't see them.

## Step 4 — Build amd64 and upload the policy

- `docker buildx build --platform linux/amd64` from `Dockerfile.llm` in the bot repo, run in
  background with a log file. The league requires amd64; Apple Silicon builds it under emulation.
- After an intended change, confirm the image ID CHANGED; after a revert, an image ID identical
  to a previously verified-good build proves byte-identical behavior — skip re-validation.
- Stale-cache trap: a buildx compile error whose line number doesn't match the current file means
  a stale `COPY . .` layer — rebuild with `--no-cache`.
- Bake `CREWRIFT_BEDROCK_MODEL=us.anthropic.claude-sonnet-4-6` into the image ENV (the advisor's
  default opus model is not enabled in the runner account and dies silently); verify with
  `docker inspect`.
- Upload: `coworld upload-policy` is broken (0.1.16; server moved ECR push to an
  `authorization_token`). Use the manual path (kept as `/tmp/upload_policy.py`, driving
  `coworld.upload` internals): request the upload, docker-login with the returned token, push to
  the returned ECR repo, complete the policy create preserving `secret_env` (USE_BEDROCK=true).
  A null `pre_signed_info` means that exact image hash was already pushed — not an error. An
  aliased policy (same image, new name) registers without a rebuild.

## Step 5 — Run the server-side league A/B

The eval is `_harness/eval.py` → `league_eval.run_league_ab` (`_harness/league_eval.py`) →
one POST `/v2/experience-requests` per arm on prod Observatory, same field/seed, requester swapped
— candidate in one forced seat, the league's top live players (or a pinned roster) in the other 7.
Both arms run concurrently (pre-resolved pvids, shared abort Event; commit 6be96c2). Candidate and
baseline must be uploaded, owned policy versions, not local docker tags.

Operational rules learned the hard way:

- **Resolve all pvids before submitting any arm** — there is no server-side cancel; a late name
  failure orphans a full run.
- **Re-resolve the roster immediately before EVERY launch.** Use
  `list_memberships(league_id, division_id, active_only=True)` — never names (ambiguous 400s),
  never round-result pvids (stale 400s), never yesterday's roster file. The league rolls policy
  versions mid-session (crewborg v19→v21→v22 in one day).
- Opponents land in **list order**; verify seat assignment from `participants[].position`, not by
  pvid uniqueness.
- Forced seat goes in `requester.slot` (nested), not a top-level field.
- `game_config_overrides` is the experiment-control surface (shallow-merged, schema-validated,
  bad keys 400): `seed` (pin it — cruxes must be reproducible; spread across a few seeds since
  two deterministic bots at one seed is one observation), `maxTicks` (10000 league-realistic;
  2000 ≈ 80 s; 300 for smokes), forced imposter slots, `killCooldown`-class difficulty knobs,
  and mechanic ablations like `buttonCalls: 0`.
- The server parallelizes episodes fully (dispatch ~100 episodes/5 s, ~2000-job cap, ~240
  warm-episode capacity) — N=30/arm is fine; the floor is realtime pacing plus ~2 min
  provisioning. Scale the poll timeout from `num × maxticks`, never a flat constant.
- Launch as background Bash with `PYTHONUNBUFFERED=1` (or `python -u`) writing to a log file, and
  watch progress with a server-side poller script (e.g. `/tmp/abmon.py`) or — for anything
  long-lived — a **persistent Monitor task** running a poller piped through
  `grep --line-buffered`. Do NOT trust nohup'd detached pollers: Python block-buffers stdout
  (empty log ≠ dead run — check `ps` and run-dir artifacts), the harness blocks foreground
  sleeps, and detached shells have died silently mid-poll more than once in this project.
- Poll loops must tolerate transient 404s right after create (read-after-write lag),
  read-timeouts on the heavy detail GET (give it ~60 s), and transient transport errors — retry
  within budget, still fail loud at zero completed episodes. A poller crash is NOT a backend
  failure: re-fetch the existing request id, never resubmit.

Ad-hoc API exploration is done with inline `uv run python - <<PY` heredocs against
`coworld.api_client.CoworldApiClient.from_login` (list requests, dump raw response shapes, probe
endpoints). Avoid piping `uv run` output into JSON parsers (sync preamble corrupts it) — call the
venv python directly when output must be machine-parsed.

## Step 6 — Read the verdict (measurement discipline)

- Per-seat wins/scores come from each episode's `results.json` (slot-indexed arrays incl. the
  authoritative imposter array; slot i = color i); the shared `wilson()` math produces
  BETTER / WORSE / INCONCLUSIVE. INCONCLUSIVE means INCONCLUSIVE — extend and pool, don't ship.
- **Calibrate the instrument before trusting it.** Verify the headline metric is in a movable
  range for the baseline: maxticks too low makes crew win structurally 0 (an entire day of fleet
  A/Bs was blind this way); weak imposters ceiling crew win at ~93–100%. If pinned at either
  extreme, change the regime (stronger opponents, kill-cooldown knob, non-binary metrics), not
  the bot.
- For imposter changes, judge primarily by **kill counts and score** — imposter win rate swings
  ±0.15 at N=30 while kills trend consistently.
- Keep dense per-arm metrics alongside win rate: vote-rate, vote ACCURACY (fraction of cast votes
  hitting a real imposter), advisor fire-rate, vote-timeouts per game (`_harness/metrics.py`,
  `analyze_votes.py`-style tools — build them once, commit them). Accuracy caught a regression
  (0.381→0.148) that timeout counts missed; conversely a fire-rate "win" hid a vote-timeout
  regression. Wrongful votes are negative-value: precision gates come before recall expansion.
- For league-round (live) comparisons use a **Welch t-test on round scores over a wide window**
  (a 15-round window misread a baseline by 4+ points), and drop league-wide collapsed rounds
  (winner score < 20) from both sides first.
- Pool same-direction deficits across related configs to clear Wilson at small n — single configs
  at n=30 overlap; pooling 3×30 separates real ~10pp effects.
- When a pre-registered gate's preconditions break (e.g. the comparator stops earning in-window
  samples so z can never fire), say so explicitly and decide on the totality of evidence rather
  than waiting on a dead rule.

## Step 7 — Explain the verdict with ground truth

When a verdict needs explaining (or seems impossible), go to artifacts, in this order:

1. **Per-seat policy logs** (`policy_agent_N.log` from the request artifacts): grep decision
   strings — `llm advisor vote <color>` / `llm advisor: skip` = real decisions;
   `llm advisor invalid -> skip` = advisor process died (creds/model); `llm timeout` = latency.
   The result JSON's `vote_timeouts=0` does NOT prove advisor health — invalid→skip is visible
   only in logs. When a grep-derived count looks impossible (fires=0), read raw lines before
   concluding — the regex may not match the live format. Always ground parsers in
   current-format artifacts pulled from a live run, never stale samples.
2. **Replay decoding — the authoritative oracle** for deaths/movement/votes: download the
   `.bitreplay` from the public S3 `replay_url`, zlib-uncompress, and run the repo's
   `src/crewrift/replay_mine.nim` tool (parseReplayBytes → initSimServer from the replay's
   configJson, which carries the resolved seed → stepReplay loop → per-slot CSV: diedTick,
   distance, tasks, full kill/vote log). A "replay hash mismatch at tick N" warning does not
   invalidate reconstruction — validate by exact match of final per-slot roles/rewards/deaths
   against the recorded scores. Note: raw input-rate stats (presses, idle%) carry no strategy
   signal — only full sim reconstruction does.
3. **Rival telemetry**: any uploading slot's player artifact is team-readable from your own
   requests — crewborg's per-tick sqlite trace.db exposes its beliefs/suspicion/vote decisions;
   rival policy logs are readable from B-arms. Mining these beats inference (one lane extracted
   the #1 ejector's exact attribution constants).
4. **Config-ablation probes**: disable a suspected mechanic via `game_config_overrides`
   (`buttonCalls: 0`) and run paired arms — one n=30/arm ablation proved the then-#1's entire
   edge was a single button press, answering what weeks of behavior-copying could not.
5. Watching a replay: `coworld replay-open <ereq_id> --hosted` (no Docker needed; sessions are
   per-user capped, expect transient 504s). Pick the paired seed where candidate and baseline
   diverged as the replay worth watching.

## Step 8 — Validation ladder, then ship

Before any league submission, escalate through (each rung gates the next):

1. Crux config at >=2 (later >=4) seeds — beat the comparator with non-overlapping CIs.
2. Opposite-role regression check (a crew fix must not tank the imposter seat).
3. Weak-field arms — **with a same-era control**: era baselines rot within hours in an active
   league (a 26–29/30 baseline became 0/30 the same day as the bottom tier strengthened). Always
   re-run the incumbent on the current field before declaring a regression; all verdicts are
   within-battery paired comparisons.
4. League A/B via `_harness/eval.py` vs the incumbent on the top-7 field.
5. **Live-mix replica arms** (binding gate, added after a candidate passed every constructed test
   and lost ~5 pts/round live): randomized division-mix fields, 7 distinct random live members
   per chunk chosen client-side (the server's `{"player": {"random": true}}` fill draws WITH
   replacement). The forced top-7 A/B isolates single changes but does NOT linearly predict
   league rank.

Then ship, with user approval:

- `uv run coworld submit` enters the policy in Qualifiers; it does NOT become champion or
  displace anything automatically. Verify with `coworld memberships --mine`.
- Run the user's two player slots as a standing live A/B: champion holds the title, the
  experiment slot carries the latest ladder-passing candidate, a dedicated Welch watcher compares
  round means, with a pre-registered cut rule (retire the experiment at z>=1.5 by n~15) so a
  regressing build doesn't bleed the lifetime mean. This live gate is the final arbiter — it cut
  tier6e at z=2.04 after 12 rounds.
- Promotion/retire via the league-policy-membership endpoints
  (POST `/v2/league-policy-memberships/{id}/retire`). Retire stale roster policies FIRST — the
  league rotates rounds among ALL live memberships, so an ancient low-mean policy mechanically
  drags the blended leaderboard mean; pruning is the cheapest gain available.
- **After ANY membership churn** (submit/retire/rotation): verify the `is_champion` flag and the
  leaderboard entry — churn silently cleared the flag and delisted the player twice in one day;
  restore via the champion endpoint. The list endpoint reads a lagging replica; a 409 on
  re-retire proves the state stuck.
- The leaderboard is a lifetime mean (~430 rounds ≈ 0.01/round movement); a rival can outrank you
  purely on a younger ledger. The remedy is a fresh player identity carrying the same image —
  but player-management routes need the user's web session (the CLI token is player-scoped), so
  stage the alias and hand the final flip to the human.

## Step 9 — Record, then loop

- Write a project memory note (one durable fact per note) + MEMORY.md index entry for every
  measured result, *including refutations*, in the same session it lands. CORRECT or DELETE notes
  in place the moment new evidence overturns them — three notes were corrected mid-campaign.
- Append the numbers to the Asana task as a story; close the task only on
  validated/refuted-with-evidence.
- Commit process changes to `docs/optimize-policy.md` / `docs/league-api.md` every time the
  method changes, so the loop survives sessions. Keep `_harness/CREWRIFT_PLAYBOOK.md` reconciled
  with live reality (the human corrected it more than once).
- Update the comparison baseline to the newest shipped policy and re-run all open cruxes
  (Step 1).
- Harness-repo changes ship by direct fast-forward push to main on the user's "merge to main"
  (no PR ceremony in this personal repo); run the pre-push gate first (tests via
  `uv run python -m unittest` from inside `_harness` with `CREWRIFT_MANIFEST` set, ruff,
  `node --check` on generated JS where relevant), and an optional `vet-bedrock` review pass.
  Bot-repo changes commit on the bot repo's own branch — the two repos have different remotes and
  default branches; resolve the push target before touching remotes.

---

## Recurring failure-handling sub-loops

These fired repeatedly; treat them as standard moves, not surprises.

**Wedged episode (0 complete, stuck "running").** Distinguish hung vs slow: sample the live
spectator websocket in two time windows — byte-identical frame sequences 15 s apart = frozen sim.
Crewrift's connect timeout is tick-based, so one never-connecting participant freezes the game at
tick 0 forever. Isolate the culprit by bisection (rerun the exact field with a known-good policy
swapped in). Add a stall-grace fail-fast to pollers (completed=0 well past a single-episode
budget → fail with "likely wedged participant"). Null `started_at`/`pod_name` on job records is
not evidence of non-scheduling.

**Server API changed under you (422s on a previously-working body).** Do not error-probe field by
field — fetch the deployed server's OpenAPI spec, conform to IT (repo HEAD and local checkouts can
be ahead of or behind prod), verify with a 1-episode smoke, then immediately update
`docs/league-api.md` and broadcast to every agent using the old shape. This happened twice: the
"backfill" field mismatch, and the 2026-06-12 rework to a unified `roster` body (one entry per
seat with policy_ref; the old requester/opponents shape now 422s).

**Backend outage triage.** Before concluding anything, run two controls: a known-good simple game
on the same backend (outage is backend-wide vs game-specific) and the same roster on the other
backend (k8s vs antfarm). Rule out cold-start with warm waits and a single-image roster. Worker
GETs returning 200 prove HTTP liveness, not that episode-start POSTs work. A 500 with
"Invalid length for parameter RoleArn, value: 0" = the backend lost EVAL_CLUSTER_ROLE_ARN — file
it (Asana Bugs project, with evidence logs and the team's attribution conventions) and arm an
event-driven recovery watch (probe script + tracked waiter that wakes the session on first
success), with cadence scaled to outage duration. External escalation only on explicit user
approval. A large pending count can be a healthy conveyor — measure drain rate (Little's law)
before scaling anything.

**Background process death.** Detached nohup pollers and subagent lanes die silently. Use the
Bash tool's run_in_background (tracked, fires task notifications) or persistent Monitor loops,
never `nohup ... &` or foreground sleeps (the harness blocks them). For multi-agent fan-outs:
every lane maintains a STATE.md checkpoint after each harvest so a fresh relay agent resumes
losslessly; audit any lane silent >1 h via workdir file timestamps; keep the xreq heartbeat
monitor running.

**Mid-edit interruption (socket drop, resent prompt).** Do not replay the edit list from the top:
rg for the added/removed symbols and git-diff the file to determine which edits landed, then
finish only the remainder.

**The advisor looks dead / the bot plays as a skip-bot.** Check in order: is `--use-bedrock` /
USE_BEDROCK actually wired (locally `coworld run-episode --use-bedrock --aws-profile softmax-org`
injects creds); is the configured Bedrock model id invokable from the execution account
(opus default was not — pin sonnet via env); is concurrency degrading it (high per-box load drove
84–100% invalid rates — run advisor-sensitive evals at low concurrency). Synthetic burst probes do
NOT reproduce sustained in-game load failures. Local realtime runs CAN validate the advisor
(check game stdout for `speed=1x`); the lab verifies the mechanism fires, never deduction
efficacy — notsus opponents barely chat, so LLM bots tie locally yet can top the league.

**Local smoke false alarms.** amd64-under-QEMU bots drop sockets (false "bot crashes"); a 300-tick
cert fixture legitimately scores all zeros; read game.stdout for connect/start/replay before
concluding anything is broken. The old crewrift-fastgame image produces zeroed invalid results on
0.1.36 — stock realtime amd64 is the valid local mode.

---

## Human steers observed as standing guardrails

- "Optimize the policy" / "unlimited budget, start optimizing" — but every promotion still gated
  through the measurement ladder.
- "Can we use larger Ns?" / "why are there no new cruxes? that's hard to believe" — challenge
  empty or underpowered results; the answer was pooling and chunked extensions, not acceptance.
- "Experience requests test against best players, but rounds run against the whole division —
  test that way too" — the live-mix replica gate.
- "When we update the policy, re-run the cruxes."
- "If you are not running xp-requests, something is wrong or stuck — schedule a monitor."
- "Are all subagents making progress?" / "you said antfarm is down, double check" — demand fresh
  probes over stale conclusions.
- "Champion just means scoring-player… you keep thinking champion means winner" — corrected the
  agent's score model; "dead crew become ghosts that complete tasks" — corrected a game-model
  conclusion; both went straight into memory.
- "Don't fallback, fail if rejected"; "make sure we can submit many xp-requests for the same
  pair" (no caching); "dont ask me, just do it" for in-loop iteration — but submissions, retires,
  and bug filings were individually approved.
- Rejected forms: skill-file deliverables (process lives in repo docs), local-Observatory
  seeding ("can we just use the experience requests api?"), SkyPilot, DynamoDB, ad-hoc AWS calls
  (CDK only), and PR ceremony on the personal repos ("merge to main").
- When a directive contradicts a recorded lesson (e.g. "always use 16 workers" vs the
  advisor-concurrency note): state the collision, then verify empirically before AND after — and
  be ready for the lesson to win.

## Superseded rungs (history, kept for context)

The loop above is the end state. Two earlier eval rungs were built and then deliberately
replaced — do not resurrect them:

1. **Local docker A/B** (`_harness/dashboard.py` / `eval.py` paired scrimmages on the Mac,
   phased arms, --bedrock for advisor work): retained only as a cheap mechanism-check lab; it
   cannot measure deduction or league strength (weak-field ceiling ~97%, no real opponents).
2. **dqueue** (Aurora Data API queue + CDK EC2 amd64 runner fleet + `_harness/queue_cli.py`,
   built 2026-06-08): solved native-amd64 throughput and produced the contested-gate methodology
   (opponent + kill-cooldown knobs, parallelism calibration), but was deleted (~5,400 lines)
   once the server-side experience-request eval proved league-faithful. The durable lessons
   carried forward: calibrate the instrument, knobs in the DB/request body not in infra, force
   slots for parallel independence, and report-early-don't-wait on long runs.
