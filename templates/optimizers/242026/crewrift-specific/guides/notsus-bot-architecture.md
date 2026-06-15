# notsus bot architecture — the already-implemented inventory and code map

Reference for the `notsus` crewrift bot — the live league reference policy
(branch `daveey/crew-vote-gate`, crewrift 0.1.36). **Read this before proposing
any behavior change.** Its whole purpose is to stop you re-porting layers that
already exist. notsus is not a beelining stub: it already has clearance-aware
A*, exact-TSP routing, a persistent log-odds suspicion model, witnessed-kill /
vent confirmation, an LLM-first vote chain with recruitment chat, and full
isolated-victim / trajectory-intercept / unwitnessed-kill imposter play. The
real open levers are narrow (ghost routing, vote conversion, presence at kills),
and several intuitive "improvements" have been **measured and refuted** — those
verdicts are flagged below so you don't rebuild them.

All line numbers are `players/notsus/notsus.nim` unless the proc is named as
`advisor.py`. The file is ~6500 lines; this is the index so you don't grep it
each time.

---

## 0. How to use this document

- **Want to change a behavior?** Find the layer below, then tune its *constants*
  (§9) rather than replacing the layer. Every named behavior is gated by a named
  constant, not a literal buried in a proc.
- **The bot "does nothing"?** Jump to §7 — it is almost always the localization
  gate, not a strategy bug.
- **Have a "make it smarter" idea?** Check §10 (refuted levers) first. Several
  plausible ideas are already measured dead.
- Content tagged **(session-derived, unverified)** comes from agent session
  notes / memory, not from re-reading the code this pass — treat it as a strong
  prior, but re-confirm against the source before acting on it.

---

## 1. The per-tick pipeline: `decideNextMask`

The single entry point is `proc decideNextMask(bot: var Bot): uint8`
(notsus.nim:5476). It runs once per frame and returns the controller-button
bitmask for that frame. Order of operations (notsus.nim:5476–5590):

1. **`updateLocation()`** — localize the camera/self on the map. If
   `not bot.localized`, the bot returns mask `0` and does nothing ("waiting for a
   reliable map lock"). **Nothing downstream runs until localization succeeds**,
   so a localization bug silently disables the entire bot (see §7).
2. **Interstitial branch** (between rounds / win screens / meetings): if
   `bot.interstitial`, then if `bot.voting`, hand off to `decideVotingMask()`
   (the entire meeting/vote brain, §5); otherwise return `0`. The vote brain is
   reached **only** here — voting logic and in-world movement never run in the
   same tick.
3. **Motion + perception refresh:** `updateMotionState()`, then
   `rememberVisibleMap()`, `updateTaskGuesses()`, `resetTasksFromRadar()`,
   `updateTaskIcons()`.
4. **Memory updates:** `rememberHome()`, `updateSightings()` (per-color last-seen
   room + position history), `updateDeduction()` (suspicion log-odds +
   witnessed-kill/vent confirmation, §4).
5. **Role branch** — crew and imposter are *fully separate subtrees*; there is no
   shared "act" function:
   - **`RoleImposter` and not ghost** → `decideImposterMask()` (hunt / search /
     prowl, §6). Imposters never run the crew task/body/vote path here.
   - **Crew (alive)** → if a body is visible (`nearestBody()`): navigate to it and,
     when `inReportRange` AND nearly stopped (`|velX|+|velY| <= 1`), press A to
     report (`reportBodyAction`). Reporting requires braking, like the emergency
     button (§3).
   - **Otherwise** → pursue the next task via `nearestTaskGoal()` (§2). If at the
     goal and ready, `holdTaskAction` (press-and-hold A for
     `taskCompleteTicks + TaskHoldPadding`); else navigate.
6. **Navigation choice for a task goal** (notsus.nim:5558–5582): a ghost or a far
   goal uses A* (`ensurePathTo` + `choosePathStep` + `maskForWaypoint`, §3); a
   mandatory task within `TaskPreciseApproachRadius` (12 px) switches to
   `preciseMaskForGoal` (exact coast-aware final approach, no A*). The final mask
   passes through `applyJiggle` (anti-stuck wiggle).

**Structural facts to respect:**

- A crew change in `decideNextMask` does not touch imposter play and vice versa.
- **Ghosts (dead crew) keep completing tasks** — the ghost branch still calls
  `nearestTaskGoal` / `navigateToPoint`, and ghosts get the *uncapped* TSP route
  (§2). Ghost routing is a zero-risk crew-win lever.

**Trigger:** when planning any change, locate your lever in this pipeline first,
and respect the localized-gate (step 1) and the crew/imposter split (step 5).

---

## 2. Task routing: exact Held-Karp open-TSP with a 1.5x detour cap

Crew task selection is **not** greedy-nearest. It is an exact open-tour TSP over
remaining mandatory tasks. This is shipped; the measured win under contested
pressure was **+21pp** (session-derived, unverified — `tsp-task-routing-beats-greedy-under-pressure`).

`proc routedMandatoryGoal` (notsus.nim:4853) collects all remaining
`TaskMandatory` goals and:

- **If `n <= RouteMaxExactTasks = 10`** (notsus.nim:4849): runs Held-Karp bitmask
  DP (`dp[mask*n+j]`, O(2^n · n²)) over the Manhattan distance matrix to find the
  minimum-total-travel open tour starting from the player, then returns the
  **first** task on that optimal tour. The cap of 10 bounds the 2^n cost; beyond
  10 tasks it falls back to nearest-first (`nearestPos`).
- **Living-crew detour cap:** for a living crewmate, if the routed first leg is
  more than 1.5× the greedy-nearest distance
  (`routedDist * RouteDetourDen > nearestDist * RouteDetourNum`, with
  `RouteDetourNum = 3`, `RouteDetourDen = 2`, notsus.nim:4850), it **reverts to
  nearest**. Rationale in the code: walking far past a nearer task isolates you and
  invites a kill. **Ghosts are unkillable so they get the uncapped optimal route**
  (`if not bot.isGhost` guards the cap).

Same Manhattan metric and same mandatory-candidate predicate as the greedy path
it replaced — only the visiting *order* changes. `routedMandatoryGoal` is
consumed by `nearestTaskGoal` (notsus.nim:4956), the single task-goal entry point
called from `decideNextMask`.

**Implications:**

- **Ghost routing is a zero-risk crew-win lever** (uncapped optimal route, ghosts
  can't be killed, and ghosts still complete tasks — §1). The cleanest remaining
  task-throughput lever. The detour cap could be relaxed/removed for ghosts'
  *route construction* if not already (it gates the first-leg revert; verify the
  uncapped path is actually being constructed, not just the revert skipped).
- **A task-throughput A/B is invisible unless the eval regime sits in the
  ~0.4–0.7 crew-win band.** At league-default kill cooldown both arms saturate
  near 90–100% and the routing change shows nothing (session-derived). Pick a
  contested regime first.

**Trigger:** any "make crew finish tasks faster / route better" idea — exact TSP
with the detour cap is already the incumbent; the open levers are *ghost routing*
and *choosing a non-saturated eval regime*.

---

## 3. Navigation: clearance-penalized A* + momentum-aware coasting steering

Two movement layers, both already tuned. The clearance-aware A* is the **first
validated crew gain over the field** (`daveey-notsus-nav`: **29/30 vs 26/30**,
session-derived `crewrift-leaderboard-gap-diagnosis`).

### Pathfinding — `findPath` (notsus.nim:3445)

A full pixel-grid A* over the walkability mask (`bot.sim.walkMask`), 4-connected,
admissible Manhattan heuristic (`heuristic`, notsus.nim:3414). `passable`
(notsus.nim:3403) requires the *whole* CollisionW×CollisionH box to be walkable,
so the path is for the body, not a point. It reuses preallocated
`pathParents/pathCosts/pathSeen/pathClosed` arrays with a monotonic `pathStamp` to
avoid per-call reallocation — a perf detail; don't naively rewrite it to allocate
each frame.

### The clearance penalty (the actual gain)

Each step costs `1 + (WallClearancePenalty if wallNear)`. `WallClearancePenalty = 1`
(notsus.nim:93). `wallNear` (notsus.nim:3435) is true when an impassable tile sits
within `ClearanceProbe = 7` px cardinally — a cheap 4-lookup proxy for a
"wall-hugging cell the collision box snags/oscillates on" (off-map reads count as
walls, so map edges are wall-near too). It is a **soft cost, not a constraint**:
tight corridors stay pathable, the heuristic stays admissible, but routes bias off
corners/edges to cut momentum snags. That softness is why it doesn't trap the bot.

### Steering — coast/brake controller

The game has momentum, so steering is not bang-bang. The mask for a waypoint comes
from `axisMask`/`preciseAxisMask` (notsus.nim:5058+) per axis:

- **`shouldCoast`** (notsus.nim:5051): if current velocity will carry the bot to
  the target, emit **no input** and coast. `coastDistance` (notsus.nim:5042)
  integrates velocity over `CoastLookaheadTicks = 8` with `FrictionNum/FrictionDen`
  decay.
- **Brake:** otherwise, if overshooting (`velocity > 1` and
  `delta <= |velocity| + BrakeDeadband`), emit the **reverse** mask to brake.
  `SteerDeadband = 2`, `BrakeDeadband = 1`.
- **Precise approach:** near a mandatory task (within `TaskPreciseApproachRadius = 12`
  px) the bot drops A* and uses `preciseMaskForGoal` so it stops *on* the task tile.

The same braking logic is why the bot must be nearly stopped (`|velX|+|velY| <= 1`)
to **report a body** or **press the emergency button** — a moving A-press doesn't
register reliably (session-derived button-mechanics note).

**Trigger:** any pathfinding or movement-smoothness change — the clearance bias and
the coast/brake controller already exist and are validated; tweak their constants
(§9), don't replace the layers.

---

## 4. Crew deduction: persistent per-color log-odds + two hard confirm rules

The crew suspicion brain already exists and is **not** a stub. It is a Bayesian
log-odds table per player color, updated every tick in `proc updateDeduction`
(notsus.nim:3972) and read by `imposterProb` (notsus.nim:4075). This is exactly
the "persistent witnessed-kill/vent + log-odds suspicion (Tier 1)" technique that
the `crewborg-techniques-to-copy` memory note flagged to port *from* crewborg — it
is already in notsus. **Do not re-port a suspicion model.**

### How it works

- `bot.suspicion[color]` holds accumulated log-odds; `bot.confirmedImposters[color]`
  is a hard flag.
- `imposterProb(c)` = `1/(1+exp(-(SuspicionPriorLogOdds + suspicion[c])))`, or
  `1.0` if confirmed. The prior is `ln(K/(P-1-K))` for K=2 imposters, P=8 players
  (notsus.nim:3792).
- **Evidence terms** (the `let` block at notsus.nim:3797):
  - `SuspicionBodyProx = ln(3.0)` — being the nearest live crew to a fresh body.
  - `SuspicionVentDwell = ln(8.0)` — lingering on a vent (only imposters vent),
    credited **once** per continuous dwell after `VentDwellFramesNeeded = 8` frames.
  - `SuspicionConfirmed = 20.0` — used by the two hard-confirm rules below (drives
    P ≈ 1).

### Two deterministic confirmations (set `confirmedImposters`, strongest evidence)

1. **Witnessed kill** (notsus.nim:4002–4036): a body appears new this frame where a
   crewmate the bot saw *last* frame was standing (within `VictimMatchRadius = 28`
   px) and is now gone, **and** exactly **one** other live non-known-imposter crew
   was within `killRange` of that spot. That single crew is confirmed the killer.
   The "exactly one" requirement is a precision gate — ambiguous scenes confirm
   nobody.
2. **Witnessed vent submerge** (notsus.nim:4037–4055): a crewmate seen on a vent
   last frame (real dwell, `ventDwellFrames >= 2`), gone now, with no fresh body
   where they stood → confirmed.

### What's measured

Porting *more* deduction did **not** improve crew win rate (**27/30 vs 29/30**,
session-derived `crewrift-tier1-deduction-result`): crew games are task-decided,
kills are isolated by design, so the witness rarely fires. **Confirm the model is
present and measure its fire rate before proposing another deduction port.** (See
also the refuted track-memory/perception lanes in §10.)

**Trigger:** any "add a suspicion model" / "port crewborg's witnessed-kill
detector" proposal — it is already here.

---

## 5. Crew vote: LLM advisor first, then a 4-rung evidence floor

When a crew bot reaches a meeting, the vote target is chosen by
`desiredVotingDecision` (notsus.nim:4686). The decision order is exact and
load-bearing:

1. **If the LLM advisor returned a valid living color → vote it** ("llm advisor
   vote <color>"). The advisor is the override layer (§8).
2. **Else fall through to `crewVoteFloor()`** (notsus.nim:4401), an ordered
   evidence chain:
   a. `confirmedImposterVotingTarget()` — a witnessed imposter (from §4's hard
      confirm), if living and safe to vote.
   b. `topSuspicionVotingTarget()` — the highest-`imposterProb` color that clears
      `SuspicionVoteThreshold = 0.5` (notsus.nim:4096).
   c. `crewBandwagonTarget()` — pile-on: join any target with ≥2 existing visible
      votes unconditionally; **or** join a lone (1-vote) target *only if*
      `suspicion[thatColor] > 0` (own corroboration), so imposter frame-jobs in
      chat/votes can't pull the vote (notsus.nim:4370).
   d. `bodySusVotingTarget()` — nearest-to-the-body heuristic (last resort).
3. If the advisor explicitly said **skip** and the floor is empty → skip. If the
   advisor errored/was invalid and the floor is empty → skip. The bot never times
   out (always emits a decision).

### Two things baked into the code as comments-as-evidence

- **The vote floor is the FULL evidence chain** (confirmed → P≥0.5 suspect →
  majority → body), not a body-only floor. Comment at notsus.nim:4716 records the
  reason: against the Competition field, **every measured crew win required an
  ejection (13/13 wins had one; 0 ejections across 47 losses)**. Abstaining is the
  costly case here — the opposite of the old task-decided field.
- **`SuspicionVoteThreshold` was deliberately lowered from 0.8 to 0.5**
  (notsus.nim:3787 comment): the 0.8 gate needed log-odds ≥ ln4 ≈ 1.39, which
  body-prox cues (`2·ln3 + prior = 1.28`) can never reach, so it fired **0
  player-votes in 30 episodes**. This is the "reachable gate" fix — it is shipped
  at 0.5; **do not re-derive or raise it**.

### Recruitment chat

`maybeQueueCrewSusChat` (notsus.nim:4415) emits one "`<Color> sus`" line per
meeting (title-cased — the format every field parser reads) targeting the
`crewVoteFloor` color, to recruit other crew onto one vote. This is the tier5c
"recruitment cascade" breakthrough, already in the code.

**Trigger:** changing crew voting — this is the live chain; any new vote source
plugs into `crewVoteFloor`'s ordered fallback, not a fresh top-level branch.

---

## 6. Imposter play: hunt / isolated-victim / trajectory-intercept / unwitnessed-kill / button bluff

The `crewborg-techniques-to-copy` note lists "trajectory-intercept /
isolated-victim / unwitnessed-kill imposter play (Tier 2)" as crewborg moves to
port into notsus, and an older note said "notsus has almost no real deduction and
beelines as imposter." **That is STALE for the 0.1.36 rewrite — all four Tier-2
techniques are already implemented.** Verify before porting.

The imposter brain is `decideImposterMask` (notsus.nim:5441), a 3-priority cascade:

1. **Isolated-victim selection** — `selectImposterVictim` (notsus.nim:5350) commits
   to the most **isolated** visible non-teammate (largest squared gap to its
   nearest other live crewmate, tie-broken by nearest to self). This is "kill the
   straggler."
2. **Trajectory interception** — `huntVictim` (notsus.nim:5394) leads the victim's
   predicted position via `victimAim`/`victimVelocity` (notsus.nim:5303), using a
   one-step sighting history from `updateSightings`. Lead is capped by
   `ImpMaxLeadTicks = 24` so a noisy velocity can't fling the aim point;
   `ImpAgentSpeedPx = 3` is the assumed travel speed.
3. **Search pre-positioning** — `searchVictimGoal` (notsus.nim:5426): when no victim
   is visible, navigate to a recently-seen victim's last-known spot (within
   `ImpTrackWindowTicks = 120`) to pre-position during kill cooldown so the first
   kill lands sooner. Falls back to `navigateProwlPoint` (random patrol over 7 fixed
   `ProwlPoints`, notsus.nim:5266 / list at 150).

**Unwitnessed-kill gate** — `killUnwitnessed` (notsus.nim:5326): the bot strikes
only when no other live crew was seen within an isolation radius recently.
Crucially the gate **relaxes with urgency** — the clearance radius
(`ImpBaseIsolationRadius = 48` px) and the witness window (`ImpWitnessWindowTicks = 72`
ticks) both shrink linearly toward 0 over `ImpUrgencyFullTicks = 240` ticks of
being able-to-kill-but-not-killing. So a cautious imposter escalates to riskier
kills rather than stalling forever against a tight crew; it does not deadlock
waiting for a perfect kill.

**Button bluff** is already present: `maybeQueueImposterSusChat` (notsus.nim:4448)
makes the imposter claim "just resetting imposter cool downs"
(`ImposterButtonBluffChat`, ~35% of meetings via `ImposterSusChatPercent = 35`) as
a fake alibi — **the bot never presses the button, it only claims to** — and it
reply-accuses anyone who called it sus ("`<color> sus`").

**Imposter votes** go through the LLM advisor with a deception prompt
(`desiredVotingDecision` imposter branch, notsus.nim:4691), falling back to
`imposterBandwagonTarget`, and never vote a teammate.

> **Imposter-strength context (session-derived):** prowl-hunt ≫ fake-tasking
> (`crewrift-imposter-ab-variance`). A strong league imposter's edge is partly the
> *button mechanic* — to isolate mechanic-vs-behavior, disable presses with
> `game_config_overrides` `buttonCalls: 0` (the other 3 spellings 400 —
> `crewrift-buttoncalls-config-key`).

**Trigger:** any "make the imposter hunt smarter / intercept / target stragglers /
avoid witnesses" proposal — all of it exists; measure the current kill rate first.

---

## 7. Perception: dual decode path + slot-based self-ID + localization gate

How notsus turns the sprite-v1 wire stream into game state. There are **two**
perception modes and a localization gate everything depends on.

### Protocol vs pixel decode

- **Protocol path (preferred):** when the server streams semantic sprite objects,
  the bot reads game state from sprite **labels** via the `protocol*` procs:
  `protocolActorLabel` (1782), `protocolBodyColorIndex` (1775),
  `protocolVoteDotColorIndex` (1806), `protocolInterstitialLabel` (1824),
  `protocolTaskMarker`/`protocolVentMarker` (598/602), driven by
  `updateProtocolDetections` (1901) and gated by `bot.protocolCameraReady`.
- **Pixel fallback:** when the protocol camera is not ready it falls back to pixel
  matching — `scanCrewmates`/`scanBodies`/`scanGhosts`/`scanTaskIcons` plus a
  camera-patch localizer (`locateByPatches`, `buildPatchEntries`,
  `framePatchHash`).

Most strategy code reads the **resolved** `bot.visibleCrewmates` /
`visibleBodies` / `taskStates` regardless of which decode path filled them, so a
*behavior* change usually doesn't care which mode is live — but a perception **bug**
may live in only one path. **Confirm which path is involved before debugging a
perception fix.**

### Localization is a hard gate

`updateLocation` (notsus.nim:1517) must set `bot.localized` before *any*
task/deduction/vote logic runs (`decideNextMask` returns 0 while not localized). A
localization regression therefore looks like a **totally passive bot**, not a
subtly-wrong one. This is the first thing to check when "the bot does nothing."

### Self-ID is slot-based and upstream

`updateSelfColor` (notsus.nim:2278) trusts the connection's `slot=N`
(`selfSlot`/`voteSelfSlot` → `selfColorIndex = slots[selfSlot].colorIndex`) rather
than inferring "self" from the centered sprite. The old pixel-inference self-ID
misread and corrupted voting (wrong self cell, self-votes, cursor desync,
timeouts); the slot fix is now **upstream** in the 0.1.36 rewrite — **do NOT
re-apply the historical local patch, it conflicts** (`_harness/CREWRIFT_PLAYBOOK.md`
§4). Self-color is excluded everywhere (deduction, victim selection, voting all
skip `c == bot.selfColorIndex`).

### Off-map guard

Off-map sprite detections carry huge i16 coordinates that overflow the
squared-distance math. `updateDeduction`, `updateSightings`, and the world-coord
converters all skip detections outside `[0, MapWidth) × [0, MapHeight)`. **Any new
code consuming `visibleCrewmateWorld`/`visibleBodyWorld` must apply the same bounds
check or it reads garbage positions.**

> **Perception is NOT the bottleneck (session-derived, `crewrift-perception-presence-not-recall`):**
> robust viewport recall ≈ 0.77 (not a recall catastrophe), frame-drops ≈ 0,
> crewborg reads the same wire protocol (no data ceiling). The victim-link failure
> is **presence/positioning** — notsus is within 120px of only 4/19 kills. The one
> bounded in-scope perception bug found: `protocolSelfObject` 12px self-drop (~22%
> of misses).

**Trigger:** debugging "the bot does nothing" (check `localized`), wrong-self
voting (slot self-ID is upstream, don't re-patch), or a perception fix (decide
which decode path first).

---

## 8. LLM advisor subprocess architecture

The vote advisor is a **non-blocking Python subprocess** that the Nim bot spawns
at the start of a meeting. Source: `advisor.py` plus
`updateVoteAdvisor`/`buildVoteSnapshot`/`applyAdvisorOutput` in notsus.nim.

### Process model (`updateVoteAdvisor`, notsus.nim:4637)

The Nim bot spawns `python3 /app/advisor.py` as a non-blocking subprocess, writes a
JSON snapshot to its stdin, closes stdin, and **keeps reading game frames while the
process runs**. It polls `peekExitCode` each tick and collects the result once the
process exits. The frame loop is never blocked on Bedrock. Any failure (spawn
error, non-zero exit, unparseable output) leaves `llmVoteColor = VoteUnknown`, so
the scripted evidence floor (`crewVoteFloor`, §5) is used — **the game always plays
even with no creds/Bedrock.**

### Model + region (advisor.py:22)

Model id comes from env `CREWRIFT_BEDROCK_MODEL`, defaulting to
`us.anthropic.claude-opus-4-7`. **The model can be swapped via env injection
WITHOUT an image rebuild** — check for the env path before rebuilding. Region:
`AWS_REGION` / `AWS_DEFAULT_REGION` / `us-east-1`. boto3 client config:
`read_timeout=5`, `connect_timeout=2`, `retries={max_attempts:4, mode:standard}` —
bounded to stay inside the `LLMVoteDeadlineTicks = 150` (~6s @ 24fps) vote deadline.

### Role-conditioned prompt (advisor.py:48–90)

One process, two system prompts keyed on `snap["my_role"]`:

- **Crew:** reasons over `players[]` with `last_seen_room` + `seen_seconds_ago`
  (-1 = never seen), `dead[]`, `chat[]` (told players lie), `votes`, `body_room`,
  `body_suspect_hint`. Instructed to **vote on any credible lead** (body proximity,
  an unseen/never-seen player, or a corroborated accusation) and only SKIP with no
  lead — "never voting lets imposters win by attrition."
- **Imposter:** told its own color and teammates (NEVER vote a teammate), given
  `body_suspect_hint`, and told to blend in — bandwagon a non-teammate to burn a
  crewmate, deflect-and-accuse if accused, SKIP if no momentum.

### Output contract (advisor.py:49–113)

The model must reply with ONE line of compact JSON
`{"vote":"<color or skip>","chat":"<=8 words or empty>"}`, vote ∈ a passed
`options` list. advisor.py extracts the `{...}` substring, lowercases the vote, and
forces any out-of-list vote to "skip". The Nim side (`applyAdvisorOutput`,
notsus.nim:4604) re-parses the last `{...}`, maps the color name via
`colorIndexForName`, and an unknown color becomes `VoteSkip`. The advisor's `chat`
becomes the bot's vote-chat line if nothing else is queued.

So the advisor is an **override/refinement layer on top of** the scripted evidence
chain, not a replacement: it sees the same body room + scripted body suspect in the
snapshot and can confirm or override them, and on any failure the scripted floor
takes over.

> **Session caution (`crewrift-vote-conversion-defect`):** a dead/invalid LLM
> advisor plus `crewVoteFloor` abstains on evasive maps was measured to eject
> **0/30** imposters vs a strong rival's 23/30. Vote conversion is a live lever;
> advisor health matters. The snapshot fields the model reasons over come from
> `buildVoteSnapshot` (notsus.nim:4489) — keep the JSON contract `{"vote","chat"}`
> or `applyAdvisorOutput` silently drops it to skip.

**Trigger:** changing the advisor model/prompt/snapshot — env-swap the model before
rebuilding; keep the JSON contract intact.

---

## 9. Tunable-constants reference

Every magic number that gates a behavior, with the behavior it gates and current
value (crewrift 0.1.36). Find the dial here instead of grepping the procs — most
behaviors are gated by a named constant, not a scattered literal. Line numbers are
notsus.nim.

### Crew suspicion / voting (defs at 3781, 3792)

| Constant | Value | Line | Gates |
|---|---|---|---|
| `SuspicionVoteThreshold` | `0.5` | 3787 | vote top suspect only when `imposterProb >= 0.5`. **Lowered from 0.8 (was unreachable); raising it silences crew player-votes.** |
| `SuspicionBodyProx` | `ln(3.0)` | 3797 | log-odds for being nearest live crew to a fresh body |
| `SuspicionVentDwell` | `ln(8.0)` | 3798 | log-odds for lingering on a vent |
| `SuspicionConfirmed` | `20.0` | 3799 | drives a witnessed kill/vent to P≈1 |
| `VictimMatchRadius` | `28` px | 3786 | how close last frame's crewmate must sit to a new body to be matched as victim. Wider = more attributions, lower precision. |
| `VentDwellFramesNeeded` | `8` frames | 3785 | vent-dwell suspicion gate |
| `VentDwellPad` | `10` px | 3784 | vent-dwell suspicion gate |
| `LLMVoteDeadlineTicks` | `150` (~6s @ 24fps) | 4480 | how long the bot waits for the advisor before the floor; also bounds advisor.py's retry budget |
| `VoteListenBaseTicks` | `VoteTimerTicks/4` | 143–145 | how long the bot listens to vote chat before acting |
| `VoteImposterSkipTicks` | — | 143–145 | imposters wait longer before skipping |

### Imposter hunt / kill (defs at 5294)

| Constant | Value | Line | Gates |
|---|---|---|---|
| `ImpBaseIsolationRadius` | `48` px | 5299 | required clearance around a victim at ZERO urgency; shrinks to 0 over `ImpUrgencyFullTicks` |
| `ImpWitnessWindowTicks` | `72` ticks | 5300 | a sighting older than this never counts as a witness (also shrinks with urgency) |
| `ImpUrgencyFullTicks` | `240` ticks | — | waiting-to-kill window over which isolation/witness gates relax to 0 |
| `ImpTrackWindowTicks` | `120` | 5296 | a victim seen within this is still trackable for Search |
| `ImpMaxLeadTicks` | `24` | 5298 | trajectory-intercept lead cap |
| `ImpAgentSpeedPx` | `3` | 5297 | assumed travel speed for interception |
| `ImposterSusChatPercent` | `35` | 159 | fake-alibi button-bluff rate |
| `ImposterButtonBluffChat` | text | 160 | fake-alibi text |

### Navigation / steering

| Constant | Value | Line | Gates |
|---|---|---|---|
| `WallClearancePenalty` | `1` | 93 | soft A* cost for a wall-hugging cell |
| `ClearanceProbe` | `7` px | 92 | how far a wall counts as "near" |
| `RouteMaxExactTasks` | `10` | 4849 | Held-Karp TSP cap; beyond this falls back to nearest-first |
| `RouteDetourNum` / `RouteDetourDen` | `3` / `2` | 4850 | living-crew 1.5× first-leg detour cap (ghosts uncapped) |
| `CoastLookaheadTicks` | `8` | 86 | coast-distance integration window |
| `SteerDeadband` | `2` | 88 | steering deadband |
| `BrakeDeadband` | `1` | 89 | brake deadband |
| `TaskPreciseApproachRadius` | `12` px | 85 | switch from A* to precise-approach near a mandatory task |
| `KillApproachRadius` | `3` | — | body/kill gate |
| `BodySuspectRange` | `64` | — | body-suspect gate |
| `StuckFrameThreshold` | `8` | — | anti-stuck gate |

**Trigger:** tuning any behavior — find the constant here first.

---

## 10. Refuted levers — do NOT rebuild these

These are measured-dead. Each carries its measurement. **Do not refile or
re-implement them.** (All session-derived from memory notes / playbook §7;
re-confirm the measurement before spending a cycle.)

### ❌ Adding / re-porting a suspicion or witnessed-kill model

Already implemented (§4). Porting *more* deduction: **27/30 vs 29/30, no gain.**
Crew games are task-decided; kills are isolated so the witness rarely fires.
(`crewrift-tier1-deduction-result`)

### ❌ Track-memory / follow-to-death victim-link / perception-recall fix

Porting crewborg's track-memory victim link fired **0/anywhere**
(witnessed-victim-link 0/30; pooled crux 23/120 vs 20/120 — overlap, no
regression). Viewport recall is ≈ 0.77 (not a catastrophe); crewborg reads the same
wire protocol (no data ceiling). **The bottleneck is PRESENCE at kills, not
perception fidelity** — notsus is within 120px of only 4/19 kills. A
recall/track-memory fix cannot see kills notsus isn't near.
(`crewrift-tier9-perception-port-result`, `crewrift-perception-presence-not-recall`)

### ❌ Crew presence / positioning / anti-isolation / group-adjacent ordering tier

Measured over 120 eps: **NOT a lever.** notsus already out-clusters league #1
(31.4% vs 28.6% within 80px); no bot witnesses kills (isolated by design);
clustering↔win is reverse causation (early-window 20% vs 17%). **Do not build a
presence / anti-isolation / group-ordering tier.** (`crewrift-presence-lever-refuted`)

### ❌ Proactive-meeting lever (call a meeting to cut kills)

**Refuted.** The game ends at imposter **parity** (4 of 6 crew removed = kills OR
vote-ejections), not "4 kills." A proactive meeting cuts kills but its vote ejects
innocents → ejection-parity loss. A strong rival (sussyboi) cuts 4-kill losses
68→5 but pays **48 ejection losses.** Next kill-suppression lever must work
**without adding a vote** (survival/positioning). (`crewrift-parity-win-model`)

### ❌ Press-timing / proactive-press tuning for crew (saturated)

The corrected two-requirement press built and validated: only ~+9pp (8/30 vs
tier5c 16/90, CIs overlap), far below sussyboi's 41%. Press tuning is **saturated.**
Residual gap is KILL SUPPRESSION (reached-4 47% vs 5.6%), which press timing does
not fix. (`crewrift-tier6e-press-result`)

### ❌ Re-applying the historical pixel-inference self-ID patch

Slot-based self-ID is now **upstream** (§7). The old local patch **conflicts** —
re-applying it re-introduces wrong-self voting / self-votes / cursor desync /
timeouts. (`_harness/CREWRIFT_PLAYBOOK.md` §4)

### ❌ Raising `SuspicionVoteThreshold` back toward 0.8

The 0.8 gate is mathematically unreachable from body-prox cues
(`2·ln3 + prior = 1.28 < ln4 = 1.39`) and fired **0 player-votes in 30 episodes.**
Shipped at 0.5; don't re-derive. (notsus.nim:3787 comment)

---

## 11. Open levers (where the gain actually is)

The narrow set still worth pursuing, distilled from the same measurements:

1. **Ghost routing (zero-risk).** Ghosts get the uncapped optimal TSP route and
   still complete tasks (§1, §2). The cleanest remaining task-throughput lever —
   confirm the uncapped route is actually constructed for ghosts, and that ghost
   task assignment / route order is optimal.
2. **Vote conversion (crew ejection).** Against the Competition field every win
   required an ejection; notsus measured 0/30 ejections vs a rival's 23/30 on
   evasive maps when the advisor was dead and the floor abstained (§5, §8). Keep
   the advisor healthy; tighten the floor's lone-target corroboration without
   re-raising the threshold.
3. **Presence at kills (imposter + crew victim-link).** The victim-link failure is
   positioning, not perception — notsus is near only 4/19 kills (§7). For the
   imposter, this is the *kill rate*; for crew, the residual gap is KILL
   SUPPRESSION via survival/positioning **without adding a vote** (§10).
4. **Choosing a non-saturated eval regime.** Many task-throughput A/Bs are
   invisible at league-default kill cooldown (both arms saturate). Run in the
   ~0.4–0.7 crew-win band so the change is measurable (§2).
5. **Mining the private #1's replays** (session-derived,
   `crewrift-truecrew-replay-mining`) — scoped, not built; needs a Nim
   `replays.nim` extraction tool.

**Always-true constraint (playbook):** crew correctness > imposter cleverness —
6/8 seats are crew, crew games are task-decided, so task throughput beats vote
logic for the average per-round score.

---

## Source map

This reference merges:
`notsus-per-tick-decision-architecture.md` (§1),
`notsus-task-routing-tsp-with-detour-cap.md` (§2),
`notsus-astar-clearance-and-coast-nav.md` (§3),
`notsus-crew-suspicion-logodds-model.md` (§4),
`notsus-crew-vote-evidence-chain.md` (§5),
`notsus-imposter-hunt-search-prowl-already-implemented.md` (§6),
`notsus-perception-localization-and-self-id.md` (§7),
`notsus-llm-advisor-subprocess-architecture.md` (§8),
`notsus-tunable-constants-reference.md` (§9),
and `docs/optimize-policy.md` (the crux-game loop these levers feed; §10–11
measurements are session-derived from memory notes and playbook §7).

Code source of record: `players/notsus/notsus.nim` and `players/notsus/advisor.py`
on branch `daveey/crew-vote-gate` (crewrift 0.1.36).
