# Refuted Levers: Do NOT Rebuild These

This is the catalog of crew-side optimization ideas that have been **MEASURED and refuted** during
the notsus campaign. Every entry below cost real cycles (build → upload → server-side A/B at
N≥30/arm → Wilson verdict) to disprove. They keep getting re-proposed because each one is
*intuitive* — the data says otherwise.

Read this before you build any crew-side change. If your idea matches an entry, the burden is on
you to explain — with a number — why the prior refutation does not apply. "It feels like it should
help" is exactly the reasoning that produced this list.

The bot is `notsus` (a Nim scripted player). Line references like `notsus.nim ~4440` point at the
source as it stood during the campaign; treat them as a starting offset, not an exact line.

---

## How to read a refutation (the method)

These dead ends were produced by the generic **descend-one-causal-layer** method (generic tier) —
the reusable artifact is the crewrift causal ladder it descended through, not any single entry:

```
vote gate → vote conversion → meeting timing → suspicion model →
  trajectory/track memory → sprite recall → PRESENCE at kills
```

Each arrow is a layer the campaign descended through. Re-tuning the top layer (the vote gate)
forever would have wasted the whole campaign; descending bottomed out at **presence at kills**,
which is a strategy/positioning constraint, not a perception or deduction bug. Most entries below
are a layer that looked like the bottleneck and turned out to be downstream of a harder one. This
campaign banked roughly ten refutations against two or three shipped wins.

**Crewrift verdict bar (the generic CI-verdict rule instantiated):** N≥30 per arm; 13%-vs-23%-scale
effects need ~100–150 episodes/arm to separate; pool same-direction deficits across related configs
only on the IDENTICAL config. The CI/extend/pool rationale is in the generic tier.

---

## Refuted Lever 1 — Crew presence / positioning / anti-isolation

### DO NOT build a presence, group-adjacent-task-ordering, or anti-isolation crew tier.

This was the team's *primary* live-form bet for "tier11": cluster the crew so they witness more
kills, then feed the dormant 100%-precision vote gate. Every link in that chain was measured and
fails. (Measured over 120 decoded seed-9001 episodes: sussyboi #1 @slot0, Boggs/crewborg @slot2 in
both arms, tier5c @slot0. Scripts + `PRESENCE_STUDY.md` in `tmp/crux/presence/`.)

1. **NO HEADROOM — we already out-cluster league #1.** tier5c spends **31.4%** of alive-time within
   80px of a living crewmate vs sussyboi (#1) at **28.6%**. The #1 bot is presence-*poor*. There is
   no clustering deficit to close.
2. **NO KILL WITNESSES — kills are isolated by design.** Even sussyboi (the best clusterer) is
   within 80px of only **10%** of kills, and that number is FLAT out to 200px; median distance to
   any kill is 336–515px. The engine spawns kills in isolation: killer is ~18px on the victim, the
   nearest crew is 180–210px away. The dormant ejection vote stack CANNOT be woken by positioning —
   it is the same starvation that fired tier9 at 0/30 and left notsus near only 4/19 kills, and it
   holds for #1 too.
3. **REVERSE CAUSATION — clustering↔win is late-game artifact.** The clustering/win correlation is
   huge late (35.5% vs 0%) but collapses to **20% vs 17%** in the early window (≤tick 1200) — the
   only window a task-order change could move. The first-kill victim is a median 307px away, 0%
   within 120px. There is nowhere to reorder to.

**Verdict:** presence is not a lever. The real crew lever is task throughput / survival-time
(the throughput-neutral early press, gated by wrongful-ejection cost), NOT presence.

---

## Refuted Lever 2 — Tier-1 crew deduction port (witnessed-kill + log-odds suspicion)

### DO NOT re-port crewborg's Tier-1 deduction as a standalone crew win. The model is faithful; the input is starved.

Ported crewborg's Tier-1 crew deduction into notsus (`daveey/llm-advisor-0136`, ~`df16878`):
per-frame witnessed-kill + witnessed-vent-submerge detectors → confirmed-imposter (P≈1); a
persistent per-player **log-odds suspicion table** (prior K/(P−1), body-proximity ln3, vent-dwell
ln8); crew vote priority witnessed-imposter → advisor → top-suspect floor.

**Result (N=30 crew, top-7 field incl. crewborg-v23): NO improvement** — candidate 27/30 vs
baseline 29/30.

The interpretation evolved as the field changed, and the *root cause* moved with it. Pin which
era's claim you are reasoning from:

- **Old (2026-06-05 field):** every game had `kills=0`; crew won by tasks, so the vote path had no
  leverage at all. This was correct *then*.
- **Corrected (2026-06-11, Competition division):** the field now hunts (~3 kills/game). Deduction
  has leverage again — **every crew win required ejecting an imposter; 0 ejections in 47 losses.**
  But tier4 cast **0.00 votes-for-players over 30 episodes**: the `SuspicionVoteThreshold = 0.8`
  gate needed log-odds ≥ ln4 ≈ 1.39 and two body-proximity events only reached 1.28. The bot
  literally could not vote without a directly-witnessed kill. truecrew:v14 (#1) in the same seat
  hit 0.43 player-votes/ep → 11/30 wins vs our 2/30.
- **Superseding (2026-06-12, `crewrift-vote-conversion-defect`):** the 0.8 gate is now STALE —
  tier5c/tier6e ship with `SuspicionVoteThreshold = 0.5` and still eject 0/30. The binding problem
  is no longer the gate, it is **EVIDENCE**: on evasive maps the witnessed-kill detector only fires
  when body + victim + killer are all on-screen in consecutive frames, so suspicion stays at the
  ~0.25 prior. Decoding Boggs vs tier6e: Boggs ejects 23/30, we eject 0/30. The fix that *would*
  work is co-location / last-seen-with-victim suspicion (Boggs's mechanism), not re-porting the
  log-odds table.

**Verdict:** the suspicion model is not the missing piece. Do not re-port deduction expecting a win
until the evidence that feeds it exists. (And see Lever 6 — even that evidence is bounded by
presence at kills.)

---

## Refuted Lever 3 — Proactive emergency-meeting / button press

### DO NOT port the rival's signature button press expecting its payoff. It carries an inseparable ejection cost, and its real edge was the button mechanic itself — not learnable behavior.

This lane burned **four** press-timing builds, all refuted. The decisive finding is a classification
trap: **copied rival behaviors don't carry their payoff.**

The league #1's single early emergency-button press suppresses kills *and* hands the field a vote
that often ejects innocents. The #1 profits only because its superior task throughput converts the
saved games. Porting the identical press into lower-throughput notsus reproduced **both** the kill
suppression AND the ejection cost — and lost more games. The live A/B cut the press build at Welch
z = 2.04.

A single config-ablation probe settled what weeks of behavior-copying could not. Disable the
button for both bots via `game_config_overrides` `buttonCalls: 0` and re-run the paired arms:

- **sussyboi's entire 41%-vs-18% edge collapsed to 6/30** without the button — below our own 10/30.
- The field's meetings were net-harmful to our bot.

So the rival's edge was the *single button press mechanic*, not a learnable strategy you can imitate
around it. Before porting any rival behavior, classify it first:

1. **Bundled-cost** — benefit inseparable from a side-effect (a meeting both stops kills and risks
   wrong ejections). You can't take half.
2. **System-dependent** — payoff depends on a capability you lack (build the prerequisite, e.g.
   task throughput, first).
3. **Surface-vs-mechanism** — you'd copy the visible action without the internal state that decides
   when to take it.

**Verdict:** the proactive-meeting/press lever is REFUTED at the strategy level. (The cheap
`buttonCalls: 0` probe is the model for settling "is the edge the mechanic or the behavior?"
questions in general.)

---

## Refuted Lever 4 — tier6e press tuning (the throughput-neutral, skip-resolving press)

### DO NOT re-tune press timing to chase sussyboi's number. Press tuning is SATURATED. The residual gap is kill-suppression, which timing does not touch.

This is the *corrected* press — built specifically to dodge Lever 3's two failure modes, and it
*worked* at what it set out to do, yet still doesn't close the gap. (Measured N=30, crux 9001,
`daveey-notsus-tier6e` pvid `91ca4339`, branch `daveey/press-tier6e`.)

Both designed requirements verified:
- **(a) throughput-neutral press WORKS:** press fires 30/30, press-tick mean ~server-1447 (on the
  ~1480 sussyboi target), team-tasks mean 43.1 (≈ sussyboi 42.7, well above the 38.8 abort floor).
  Not the throughput tank tier6c was.
- **(b) skip-resolving own meeting WORKS:** own-press meeting resolves to SKIP 30/30, our own
  player-votes ~0.13/ep, zero self-inflicted ejections.

**Result: tier6e 8/30 = 26.7% (Wilson 0.142–0.444) vs tier5c 16/90 = 17.8% (0.112–0.269). CIs
OVERLAP → NOT significant at n=30; only ~+9pp.** Far short of sussyboi's 41% and the `buttonCalls=0`
ceiling.

**Why timing tuning cannot close it (the non-obvious part):** the residual is **KILL SUPPRESSION**,
not press timing or ejections. reached-4-kills 14/30 = 47% (sussyboi 5.6%, tier5c 75.6%): one
well-timed press only delays kills ~17s and the imposters still reach parity in ~half the games.
Press timing does NOT discriminate wins from losses (win-press median 1385 vs loss 1378 — nearly
identical; presses in the 1450–1550 "sweet spot" won only 3/7). **A timing-variance re-tune will
not close it.**

A second, smaller leak: field-called body meetings eject our crew (ejection-aided losses 8/30;
field `vote_players` mean 2.6/ep) because `crewBandwagonTarget` (`notsus.nim ~4440`, the ≥2-vote
pile join) joins wrongful field piles on evidence-scarce maps. Requirement (b) only gates OUR OWN
meeting, not field meetings.

**Verdict:** press tuning is saturated. Reproducing sussyboi's press *timing* does not reproduce its
*kill suppression*. The next lever is whatever makes the press actually hold imposters to 2 kills
(crew survival/positioning in the post-press window) PLUS a map-conditional gate to stop
`crewBandwagonTarget` joining field piles when our own suspicion is empty.

---

## Refuted Lever 5 — Recall expansion without a precision gate (tier8b, vote-cursor persistence)

### DO NOT widen attribution recall or "vote more often" before gating precision. Wrong votes are NEGATIVE value.

Two independent measurements show the same thing: in crewrift, casting MORE crew votes on weaker
evidence scores **worse** than abstaining. Wrong ejections (and wrong votes generally) cost more
than the timeouts/skips they replace. (Session-derived, unverified — needs human review; two
sessions, image rebuilt to the verified-good hash on revert.)

- **tier8b — kill-attribution recall expansion:** widening attribution (last-seen-near-victim with
  first-pass parameters) without a precision gate fired **253 times with ZERO correct ejections**,
  and scored worse than the abstaining incumbent (pooled **14/120 vs 22/120**). Precision gates must
  come *before* recall expansion.
- **Vote-cursor persistence:** persisting the last-known vote cursor across frames (to cut the
  ~0.5/game vote-timeouts from stateless cursor perception) cast **+29% more votes (21→27)** but
  **dropped crew vote-accuracy 0.381→0.148 (correct votes 8→4)**. Pressing A on a stale cursor
  belief produces wrong votes. A safe version needs dead-reckoning from your own press edges plus a
  deliberate skip near the timer — and validation at N≥30, not the n=6 it was first judged on.

**Verdict:** both are the generic "precision before recall — wrong action is negative value" rule
(generic tier) measured live in crewrift: a "vote/act more often" or "remember more candidates" change
that doesn't gate precision first scores below abstaining. Banked so the lever isn't rebuilt.

---

## Refuted Lever 6 — Track-memory victim-link port (tier9, tier8b corroboration, tier8c range)

### DO NOT re-attempt a deduction/suspicion/track-memory port for the crew victim-link win. The whole lane is closed.

tier9 ported crewborg's PERCEPTION layer (per-color trajectory / proximity-interval memory →
follow-to-death victim link, `_follow_log_lr` ln6 ramp) into notsus (`daveey/perception-tier9` @
`354ce84`, policy `daveey-notsus-tier9:v1`, uploaded NOT fielded).

**Measured (paired N=30 vs tier5c @seat0, seeds 9001/4242/7777/5555): the follow-to-death path
fired 0 episodes across EVERY seed.** witnessed-victim-link 0/30 @9001 (target was ~20/30). Pooled
crux tier9 23/120 vs tier5c 20/120 — CIs OVERLAP, no separation. Imposter seat 27/30 (no
regression; crewmate-only change).

**Root cause (proven at the perception layer, not inferred):** a sustained visible shadow
(follow-to-death) is strictly HARDER to observe than the one-frame witnessed kill that *already*
never fires. crewborg's ~23/30 victim links do NOT come from engine omniscience — see Lever 7 — they
come from being *present* at kills so the proximity intervals actually form. A track-memory layer
over a stream that never sees the kill cannot manufacture sightings that never happened.

The full closed set: **tier8b (corroboration), tier8c (body-suspect range), tier9 (track memory) —
all refuted.** The suspicion model AND the per-color track memory that feeds it are both faithful
and both starved upstream. Extraction spec: `tmp/crux/runner3/CREWBORG_PERCEPTION.md`.

**Verdict:** do not re-port deduction/track-memory for the victim-link win. Before any such fix,
check the presence number (Lever 7). If it's low, the lever is positioning, not memory.

---

## Refuted Lever 7 — "Fix sprite-vision recall" (tier10 supersedes the recall-ceiling diagnosis)

### DO NOT chase a perception/recall fix for the victim-link gap. Recall is ~0.77, not a catastrophe. The bottleneck is PRESENCE at kills — a positioning problem.

This entry **supersedes** the tier9 note's claim that the gap is "sprite-vision recall." That claim
was wrong; tier10 measured perception directly against replay ground truth and overturned it. (8
eps @9001 crux, seat 0 + live top-7; telemetry build `daveey-notsus-tier10tel` + `replay_vis` exact
server-visibility decoder + anchored frameTick→gametick join.)

- **Robust viewport recall ≈ 0.77**, fairly uniform by distance (kill-range ≤20px = 0.785). NOT a
  50% catastrophe. The naive nearest-self-position join reports a FALSE ~50% because the spawn
  huddle maps one self-pos to ~140 ticks — use an anchored linear tick map.
- **Frame-dropping is REFUTED** as the cause: notsus's drain-and-collapse loop drops ~28 frames
  across 8 full games (~0). It keeps up with the ~24fps server.
- **crewborg reads the SAME Sprite-v1 wire protocol** — its `decoder.py` is ported from notsus's
  `applySpritePacket`. There is NO engine-omniscience data advantage; the server does LOS for both.
  (This corrects the "data ceiling" framing in the runner2/3 and crewborg-techniques notes.)
- **THE BOTTLENECK IS PRESENCE/POSITIONING:** across 8 games and 19 deaths, notsus is within 120px
  (= 2× viewport) of the kill at the death tick in only **4**. notsus task-routes alone and is
  almost never present at a kill. That is *why* tier9 follow-to-death fired 0/30 — the proximity
  intervals never form.

One real but bounded perception bug worth a clean fix: `protocolSelfObject` drops any player within
12px of screen-centre as "self" (~22% of misses, erasing the closest co-locations). A clean fix
excludes a centre sprite as self ONLY when its colour == `selfColorIndex` — but `selfColor` is
partly bootstrapped BY that radius check pre-first-meeting, so keep the radius as the bootstrap and
add the colour guard. **Upside is capped by presence (~4/19 kills) and by crew games being
task-decided** — do not expect this bug-fix to move the win rate much.

**Verdict:** a track-memory/recall fix cannot manufacture sightings of kills notsus isn't near.
Before building any victim-link/deduction/perception fix, check deaths-near-notsus first; if low,
the lever is positioning (a strategy change) — which loops back to Lever 1 (presence), already
refuted as a clustering tweak. The remaining honest crew lever is TASK throughput (ghost routing is
zero-risk — dead crew still complete assigned tasks). Artifacts: `tmp/crux/runner4/`
(`RECALL_REPORT.md`, `replay_vis.nim`, `recall_robust.py`).

---

## A note on what is NOT refuted (so this list isn't read as "everything is hopeless")

- **Imposter prowl-hunt play is a genuine win, not variance.** An earlier "imposter A/B is just
  variance" claim was retracted: the 12/30-vs-0/30 gap (score 55.7 vs 11.3) was a REAL code
  difference — a dirty working tree had bundled a prowl-hunt imposter rewrite
  (`navigateProwlPoint`, hunt-from-first-tick, `killWitnessPresent`, "never fake tasks") into the
  Tier-1 commit on top of the old fake-tasking imposter. **prowl-hunt ≫ fake-tasking.** Lesson:
  `git status`/`git diff` the bot repo before committing — a dirty tree silently bundles WIP and
  confounds attribution. Imposter A/B *can* detect large effects; its reliability for *small*
  effects is still untested.
- **Crew task throughput / ghost routing remains the live lever.** Every refutation above points
  back here. Crew games are task-decided; ghost routing is zero-risk (dead crew complete tasks);
  TSP-style routing beats greedy under pressure. That is where to spend cycles, not on presence,
  deduction, press tuning, or perception.

---

## Quick reference — the do-not-rebuild table

| # | Lever | Verdict | Key number |
|---|-------|---------|-----------|
| 1 | Crew presence / clustering / anti-isolation | REFUTED | out-cluster #1 already (31.4% vs 28.6%); within 80px of only 10% of kills |
| 2 | Tier-1 deduction port (standalone) | REFUTED | 27/30 vs 29/30; 0.00 player-votes/30ep; evidence-starved, not model-starved |
| 3 | Proactive press / button port | REFUTED | edge was the button mechanic; `buttonCalls:0` → sussyboi 41%→6/30 |
| 4 | tier6e press timing tuning | SATURATED | 8/30 vs 16/90, CIs overlap; residual is kill-suppression not timing |
| 5 | Recall expansion / vote-more (no precision gate) | NEGATIVE VALUE | tier8b 253 fires, 0 correct ejections; cursor +29% votes, accuracy 0.38→0.15 |
| 6 | Track-memory victim-link port (tier8b/8c/9) | LANE CLOSED | fired 0 episodes across every seed |
| 7 | Sprite-recall fix for victim-link | WRONG TARGET | recall ≈0.77 (fine); near only 4/19 kills — PRESENCE is the bottleneck |
