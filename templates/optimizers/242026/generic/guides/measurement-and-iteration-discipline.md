# Measurement and iteration discipline

A self-contained reference for iterating on any system whose behavior you measure rather than prove —
optimizing code against a benchmark, tuning a heuristic against a metric, improving an agent or model
against an eval, or any "change it, run it, see if it got better" loop. Every section is a general
principle with no domain in it. (The principles below were distilled from a long software-optimization
campaign where each one cost real cycles to learn; they generalize past that origin.)

The through-line: **when you cannot prove a change is better and can only measure it, almost every
shortcut is a way to fool yourself.** Measuring too few samples, trusting one alarming reading,
re-rolling until you like the answer, copying a trick that worked elsewhere, deleting a failed
experiment, treating a crash as a result — each one quietly corrupts the search. The discipline below
exists to stop that.

---

## 1. Measure, don't vibe

A change feels better, looks better in the one run you watched, or *should* be better by your model of
the system. None of that is evidence. The only thing that licenses "this is an improvement" is a
measurement that survives its own uncertainty.

This sounds obvious and is constantly violated, because a plausible mechanism is psychologically
indistinguishable from a confirmed one. The defense is procedural: decide the metric and the
acceptance bar *before* you run, and let the number — not the narrative — decide.

---

## 2. Confidence-interval verdicts, not point estimates

A raw mean, a single score, or a "12 out of 20" point estimate is not a verdict. Two measurements that
differ can easily be the same underlying quantity seen through noise.

- **Use an interval, not a point.** Compute a confidence interval around each arm's result (for a
  win-rate-style proportion, a Wilson interval is the standard, well-behaved choice). The verdict is a
  comparison of intervals, not of the centers.
- **Overlapping intervals mean INCONCLUSIVE.** Not a small win, not a "trend" — inconclusive. Treating
  an overlap as a win is the single most common way a measured loss gets shipped as a gain.
- **Pick the sample size from the effect size you need to detect.** Small effects need large samples:
  separating two rates that sit ~10 percentage points apart can take ~100–150 samples per arm before
  their intervals clear each other. A handful of samples can only detect large effects.
- **Small-sample "wins" flip sign.** A result that looks like a win at very small n routinely inverts
  to a loss at an adequate sample. Never promote anything on an underpowered read.

The point of the interval is not statistical ceremony — it is to stop you from acting on noise that
*looks* like signal.

---

## 3. Extend, don't re-roll

When a result is directionally interesting but its interval hasn't separated yet, there are two things
you can do, and only one is honest.

- **Extend (correct):** add more samples to the **identical** setup — same configuration, same
  conditions, same comparison — and pool them with what you already have. The interval tightens and
  the verdict sharpens. Add in chunks and re-check.
- **Re-roll (wrong):** throw away the run and start a fresh one hoping for a cleaner answer. This
  discards real signal and, worse, invites cherry-picking — you stop re-rolling exactly when the
  answer flatters your hypothesis, which biases the result toward whatever you wanted.

Pooling is only valid across runs that are genuinely the *same* setup. If any condition differs
between chunks, they are not poolable and combining them is a different error.

**Pooling same-direction signal.** A related move: when no single configuration's interval separates
but several *related* configurations all lean the same way, pool the same-direction results across
them to clear the bar that no single one could. This finds real small effects that hide under
per-configuration noise — but only pool configurations that are actually comparable, and only when the
deficits point the same way. Pooling opposite-direction or unrelated results manufactures a verdict
that isn't there.

---

## 4. Reconstruct before you believe

A single surprising observation — one bad run, one round where things looked worse, one anomalous
reading — is almost always noise. Acting on it directly is how a phantom problem eats a day.

Before treating any one-off observation as real, **reconstruct it at an adequate sample under
controlled conditions.** Pin down the exact setup that produced it, re-run it enough times to get an
interval, and see whether the effect survives. Most "it got worse" observations dissolve into variance
the moment they are reconstructed; the few that survive are real and now have numbers attached.

This also applies to a reading that seems *impossible* — a metric that's pinned, a counter that says
zero, an effect that's far too large. Go to the underlying artifact and reconstruct what actually
happened from ground truth before you trust *or* dismiss the summary number. Summary statistics lie by
omission; a full reconstruction from the raw record does not. (Raw activity stats — how often something
acted, how busy it was — usually carry no signal about *quality*; only a reconstruction of outcomes
does.)

---

## 5. Refutations are results

A measured negative is not a wasted cycle — it is a durable finding, as valuable as a win and often
more reusable. The asymmetry is real: a confirmed dead end stops an entire family of future attempts,
while a win opens only one door.

- **Record every refutation with its numbers**, precisely enough that nobody — including future-you —
  rebuilds the dead lever. Vague "that didn't work" rots; "intervention X fired N times with zero
  effect on metric Y at sample Z" is permanent.
- **Expect a high refutation-to-win ratio.** A productive campaign banks many measured negatives
  against a few shipped wins; that ratio is normal, not a sign of failing. The negatives are what keep
  the search from looping back over ground already covered.
- **A measured result is a claim about the CURRENT system, not a permanent law.** Every significant
  change can re-open old questions — so re-run the open negative checks after each change. They double
  as a regression guard: a dead end the change accidentally fixed gets closed with numbers; one it
  re-broke gets caught.

When you record a refutation, pin *which version of the system and which conditions* it was measured
under. A result's interpretation can shift as the surrounding system changes — the same intervention
can be inert for one reason early and inert for a different reason later. The numbers are durable; the
*explanation* may need updating, so date and version it.

---

## 6. The descend-a-causal-layer debugging method

The highest-leverage move when an intervention fails is also the least intuitive: **do not re-tune the
layer you just touched.** If you copied or built a capability and it didn't move the metric, the
problem is almost always *downstream* of where you were working. Drop one layer down the causal stack
and measure there.

The pattern, abstractly: an outcome depends on a chain of preconditions —

```
final outcome ← decision logic ← the evidence that feeds the decision ← the perception/inputs that
produce the evidence ← the positioning/state that makes those inputs available at all
```

When the top layer fails to help, the binding constraint is usually one of the lower ones. Re-tuning
the top layer forever burns the whole campaign; descending the chain bottoms out at the *real*
constraint — which is frequently a structural or strategic limit, not a logic bug you can tune away.

Two tells that you're working the wrong layer:

- **The mechanism you added "never fires."** If a new decision path triggers zero times, no amount of
  tuning *its* parameters matters — the layer that should feed it isn't delivering. Go down.
- **A faithful port of a working capability does nothing.** If you copied something that demonstrably
  works elsewhere and it's inert here, the copied layer is fine and *starved* — the layer beneath it
  (the evidence/inputs it needs) is the actual gap.

The reusable artifact of this method is the **ladder of layers you descended and ruled out**. That map
("it's not the decision logic, not the evidence model, not the perception fidelity — it's that the
required inputs never occur") is worth more than any single fix, because it tells the next person where
*not* to dig.

---

## 7. Precision before recall — wrong action is negative value

Doing the wrong thing is worse than doing nothing. A change that makes the system **act more often** or
**consider more candidates** does not get credit for the extra volume — it gets charged for the extra
*mistakes*. In any setting where a wrong action carries a cost (and almost all do), more volume on the
same quality of evidence scores worse than abstaining.

So:

- **Any "do more / remember more / fire more often" change must measure accuracy ALONGSIDE volume.**
  Volume alone is not improvement. A change that raised activity while dropping correctness is a
  regression even though the activity counter went up.
- **Put the precision gate in BEFORE you widen recall.** Expanding what the system attempts without
  first making sure it attempts the *right* things floods the output with confident wrong actions.
  Recall expansion on an ungated mechanism is reliably negative.
- **Watch for the metric that hides the regression.** A coarse counter (timeouts avoided, actions
  taken) can show a "win" while a quality metric (accuracy of those actions) silently craters. Track
  the quality metric explicitly; the volume metric will not warn you.

---

## 8. Classify before porting — copied behaviors don't carry their payoff

The most seductive wasted work is copying a technique that visibly works in another system and
expecting its results. They rarely transfer, because the payoff usually lives in the surrounding
context, not the copied surface. Before porting anything, classify *why it works where it works*:

1. **Bundled-cost.** The benefit is inseparable from a side-effect. The original profits despite the
   cost because of some *other* strength it has; copy the behavior into a system without that strength
   and you import the full cost with a fraction of the benefit. You cannot take half.
2. **System-dependent.** The payoff depends on a capability the source has and you lack. The behavior
   is downstream of that capability — build the prerequisite first, or the port is inert (see §6).
3. **Surface-vs-mechanism.** You'd copy the visible action without the internal state that decides
   *when* to take it. The action is the easy 10%; the judgment about timing/targeting is the load-
   bearing 90%, and it doesn't come along for free.

Also: **measure the existing fire-rate before porting.** A surprising amount of "missing" capability is
already present and simply never triggers under real conditions — porting it again changes nothing.
Check what's already there first.

**The cheap causal ablation.** Often you can settle "is the edge the *mechanism* or the surrounding
*behavior*?" with one experiment instead of weeks of imitation: disable the suspected mechanism for
*both* the source and your system and re-measure. If the source's whole edge collapses when the
mechanism is off, the edge was the mechanism — copying the behavior around it was never going to work.
One well-chosen ablation can answer what a long imitation campaign cannot.

---

## 9. Negative controls — name and keep your failed experiments

A failed experiment has durable value only if it is written down precisely enough that nobody re-runs
it. Delete it and it comes back as a "fresh idea" next month.

Give every failed candidate a **stable name and a complete record**: the exact identifier, the one or
two things it changed versus the prior version, the deterministic conditions it was tested under, the
result vector it produced, where its artifacts live, and a one-line verdict naming *why* it failed the
bar. That record buys two things a deletion never does:

- **It separates "this approach is wrong" from "this approach alone is insufficient."** A knob that
  failed as a standalone change might still be a valid ingredient composed with something else — but
  only a recorded result vector lets you tell those apart.
- **A bracket of recorded failures maps the SHAPE of the problem.** Sweeping a parameter and recording
  the result at each point *locates the cliff* — and locating the cliff tells you the next attempt
  needs a different *mechanism*, not another tweak of the same knob. "This whole family of tweaks is
  exhausted" is itself a high-value durable result that prevents an infinite re-sweep.

Keep these named negatives somewhere they persist across sessions and across people, not just in the
head of whoever ran them.

---

## 10. Terminal evidence — wait for the run to finish, and tell infra failure apart from a result

Two ways a not-yet-final reading fools you:

- **Partial reads drift.** Inspecting the completed subset of a still-running batch produces a
  plausible-looking conclusion that repeatedly fails to hold once the batch finishes. Among multiple
  point-in-time reads of the same run, **the terminal one wins.** A partial read is hypothesis-shaping
  only — never a verdict.
- **Single-sample whiplash.** One round/run/trial can swing wildly — the same configuration can look
  best and then worst in consecutive trials. One good or bad trial is noise. Wait for a broad completed
  result before drawing a conclusion, and don't let one favorable trial trigger an action you'll have
  to undo.

And the failure that masquerades as a result:

- **An infrastructure fault is not evidence about your change.** A crash, a timeout, an environment
  error, a wedged run — none of these say anything about whether your change is good. Before you revert
  or conclude, **run a known-good control on the same infrastructure.** If the control also fails, the
  problem is the harness, not your change; fix the harness and re-measure. Reverting a good change
  because the test rig broke is a classic self-inflicted loss.

A corollary for lagging, cumulative signals: when the headline number is a slow-moving average over a
long history, a genuinely-better new entrant can stay behind a long-established one for a while purely
because of the averaging window. Do not "fix" a still-converging ranking with more churn — you are
fighting the window, not a real deficit, and each churned restart resets the clock. Confirm
improvement on a *direct* controlled comparison, and let the lagging aggregate catch up on its own.

---

## How these compose

These are not ten independent tips; they are one honest loop with a guard at each stage:

1. **Frame** — decide the metric and bar before running (§1), so the narrative can't override the
   number.
2. **Read correctly** — intervals not points (§2), terminal not partial (§10), so noise never reads as
   signal.
3. **Sharpen** — extend and pool the identical setup (§3) rather than re-rolling, so the verdict
   converges honestly.
4. **Verify surprises** — reconstruct any alarming or impossible reading from ground truth (§4) before
   acting on it.
5. **Debug down, not sideways** — when a fix fails, descend a causal layer (§6) instead of re-tuning
   the one you touched.
6. **Guard against negative-value changes** — gate precision before recall (§7); don't reward volume.
7. **Don't import phantom payoffs** — classify a technique before porting it (§8); ablate to find the
   real source of an edge.
8. **Remember everything** — record refutations (§5) and named negative controls (§9) so the search
   accumulates instead of looping.
9. **Don't act on a broken rig** — separate infrastructure failure from a real result (§10) before you
   revert or ship.

Skip any one and the failure shows up downstream wearing the wrong costume: a noisy round looks like a
regression, a starved layer looks like a logic bug, a crashed harness looks like a bad change, a
volume bump looks like progress, a discarded failure looks like a fresh idea. The discipline is what
keeps the signal honest.
