# Cross-coworld craft: transferable league-iteration discipline

Reference for the generic, world-agnostic craft of iterating a scripted player against any
coworld/tournament league. None of this is specific to any one world's bots, maps, or scoring — it is
the distilled operating discipline that holds across worlds. It was extracted from a sibling coworld
(a separate league in the same family that burned dozens of build iterations learning these the
hard way), and it generalizes to any league where you ship a container into a hosted matchmaker and
read scores back.

Read this when you are about to:

- reuse a container image or build from a *sibling* league and wonder whether it will even connect;
- decide whether a candidate that won the case you were targeting is ready to upload;
- read a leaderboard or an in-progress round and draw a policy conclusion from it;
- throw away a failed experiment (don't — file it);
- operate two owned identities in the same division.

The through-line: **a coworld league is an adversarial, mixed-role, lagging-signal system. Every
shortcut — assuming protocol compatibility, gating only the slot you care about, trusting one round,
discarding failures, renaming identities — is a way to fool yourself. The discipline below exists to
stop that.**

---

## 1. Match the world's wire-protocol *family*, not the commissioner key

Two different coworld leagues can share a game-family name or even an identical commissioner/game key
and still run **completely incompatible** player wire protocols. A name match is not a protocol match.

In the source world, a new league's commissioner key matched an older league's, but the new world
spoke a different websocket protocol — a sprite/binary protocol where the old one was text. The
previously-working containers for the "same" game were **rejected outright and could not even
connect.** The shared key bought nothing.

Rules that generalize:

- **The published participant guide / protocol docs are the contract.** Before reusing any image
  from a sibling league, verify the protocol family of the *canonical downloaded coworld* you are
  actually entering. Do not let a key match, a repo name, or "it worked last season" stand in for
  that check.
- **Slot identity comes from the runtime-supplied player websocket URL** — the env var the
  tournament injects into your container — **not** from a separate command channel, a hardcoded
  color, or a seat index. Read your identity from that URL.
- **The env-var contract drifts between runner versions.** The canonical hosted contract may name one
  variable while an older local runner still reads a legacy name. Export *both* names from the
  container as a bridge, but treat the **canonical hosted variable as the source of truth** for any
  hosted evidence; the legacy name is a local-only convenience, never the thing you trust.

Cheapest possible failure: the container that can't connect. Spend the protocol-family check up front
and you never debug a phantom "my bot scores zero" that is really "my bot never joined."

---

## 2. Gate a candidate across the FULL role/slot matrix — not just the slot you targeted

In a mixed-role league your bot occupies one or two of N seats and the rest of the field fills the
others. **Tuning a single behavior knob almost always trades one role's score for another's.** A win
in the slot you were targeting is a *hypothesis*, not an upload candidate.

The source world proved this brutally. A hunt/aggression delay that turned a weak imposter slot from
a near-zero into a repeatable `120` **collapsed the crew average to single digits in the same image.**
"Improving the imposter" and "preserving the crew" sat on opposite sides of a cliff: between two
adjacent delay values, the crew average fell from **~108 to ~4** while the imposter score jumped. One
knob, one image, two roles pulling in opposite directions.

The discipline this forces, before any upload:

- **Run the candidate through every relevant case:** each owned slot alone, the paired multi-slot
  case (when you hold more than one seat), and all-slots self-play. The same image that wins the
  target slot routinely fails the *other* role it must also fill.
- **All-slots self-play that hands the aggressor role a huge score while the cooperative role
  collapses is a TRADEOFF SIGNAL, not strength.** Do not read "looks strong when every seat runs this
  image" as champion-ready. Self-play that rewards one role at the expense of another is exactly the
  failure mode you are screening for.
- **Stop the matrix early on the first failing case.** You do not need to finish the grid to know a
  candidate is no-upload. A single confirmed regression in any role disqualifies it.

A single-slot improvement is real engineering signal — keep it as a hypothesis for future
role/slot-conditioned work. But it is **not a champion until it preserves your owned scores across the
whole matrix.**

---

## 3. Wait for terminal *completed* evidence — not single-round whiplash or partial active counts

Live leaderboards swing round to round, and an in-progress round's episode counts are point-in-time
API reads that **drift while you look at them.** Two distinct traps, both seen in the source world:

- **Single-round whiplash.** The same owned champion finished **#1 in one round and then 5th–18th in
  the very next round** of the same league. One good or bad round is noise, not a verdict. Keep the
  current champion until terminal evidence from a later round — or a broad completed local gate —
  says otherwise.
- **Partial active-round evidence.** Inspecting the *completed subset* of a still-running round
  produces a plausible-looking hypothesis (e.g. a routing variant "narrowly ahead"), and that
  conclusion **repeatedly failed to hold once the round finished terminally.** Active partial reads
  are hypothesis-shaping only — never a verdict.

Operating rules:

- **Among multiple point-in-time reads of the same round, the terminal one wins.** Prefer the newest
  *terminal* capture before any policy conclusion.
- **Public rolling leaderboards LAG.** An established entrant carries many rolling rounds of history,
  so a strong new candidate can be locally- and live-proven yet still sit low on the public board
  until enough scheduled wins decay the old average. **Do not "fix" a still-decaying ranking with
  more uploads** — you are fighting the averaging window, not a real deficit, and each churned upload
  resets the clock.
- **A real replacement decision must clear a broad completed gate** — a terminal round or a full
  local matrix — **not** a single low-case win or one favorable round.

> The "broad completed gate" instantiates as the project's own measurement bar — a paired A/B at the
> minimum-n floor with confidence-interval verdicts (generic tier), run across the role/slot matrix of
> §2. The project tier names the concrete n-floor and the CI machinery for the specific league.

---

## 4. Record every failed candidate as a NAMED "no-upload" negative control

A failed experiment has durable value **only if you write it down precisely enough that nobody —
including future-you — re-runs it.** The source world did this religiously: every rejected image got a
stable name, the seed it was tested on, the per-slot scores it produced, the artifact directory, and
an explicit verdict — *"reusable builder option and negative control, not an upload candidate."*

A good no-upload note carries:

- The exact **candidate name/tag** and the one or two **build knobs** it changed versus the prior
  variant.
- The **deterministic seed** and the **per-slot score vector** it produced, so the result is
  reproducible.
- The **artifact path** where logs/results live.
- A **one-line verdict** naming *why* it fails the upload bar — e.g. "fixes slot-1 crew collapse but
  slot-7 imposter still scores 10 and the paired check times out."

Two payoffs this format delivers that a deleted experiment does not:

- **A knob that failed as a champion can still be a reusable builder option.** The next candidate can
  compose it with a different change. Distinguish "this knob is *wrong*" from "this knob *alone* is
  insufficient" — only a recorded per-slot vector lets you tell them apart.
- **A bracket of rejected values maps the SHAPE of the tradeoff.** A delay swept 50→250 and recorded
  at each point *locates the cliff* — and locating the cliff tells you the next attempt needs a
  different *mechanism*, not another tweak of the same parameter. The conclusion "simple delay sweeps
  are exhausted here" is itself a high-value durable result that prevents an infinite re-sweep.

> Where these named negatives persist is a project-tier concern: the project keeps them in its durable
> loop tracker (one record per failed candidate, attached to the idea it came from), not just in an
> agent's memory. The format above is the per-note content; the tracker is where it survives sessions
> and agents.

---

## 5. Run two owned identities as swappable blue/green lanes — don't churn-rename

When you hold two player identities (slots) in the same competition division, operate them as a
**blue/green pair**, not as two independently-managed entries:

- **Derive the lane assignment from LIVE RANK each cycle.** The lower-ranked owned identity is the
  editable **candidate lane** for the next proven replacement; the higher-ranked owned identity is
  the **protected lane.** Aim every replacement upload at the lower lane *without regressing the
  protected lane.*
- **Treat the two identities as equivalent, interchangeable deployment slots.** A newly placed
  submission for a player *becomes* that player's champion and automatically de-champions that
  player's previous active version. So you iterate by **uploading the next candidate** — not by
  removing and re-adding memberships.

What NOT to do — each of these caused real churn in the source world:

- **Don't remove or resubmit a champion entry just to rename it, and don't edit the league's data
  stores directly.** Naming cleanup is presentation-only; it must never drive an upload decision.
- **Don't add code that maps historical policy names onto lane labels.** Lanes are a *live-rank*
  concept, not a compatibility layer. The moment "which lane is this" depends on a name-history map,
  you've built a backwards-compatibility shim where a rank lookup belonged.
- **After a FAILED lower-lane experiment, don't go hunting through old identity-specific submissions
  to "roll back."** Keep iterating on *new* candidates once local gates pass. Only during an explicit
  check-in do you reset the pair to the two best proven results.

**Pairing trick that falls out of two-lane ownership:** in a head-to-head world you can make one lane
play a **support role that feeds the other lane's score** instead of splitting the prize — useful
when dividing the board between your two entries would drop one of them behind a rival. Two owned
slots are a coordination asset, not just two shots on goal.

---

## How the five compose

These are not five independent tips; they are one pipeline with a checkpoint at each stage, and each
guards the next from a different way of fooling yourself:

1. **Connect** — match the protocol family (§1), or nothing else matters; an image that can't join
   scores zero for reasons unrelated to its policy.
2. **Gate** — clear the full role/slot matrix (§2), so a one-slot win never masquerades as a
   champion.
3. **Confirm** — demand terminal completed evidence (§3), so round-to-round noise and lagging boards
   never trigger a churned upload.
4. **Record** — file every failure as a named negative control (§4), so the search has memory and the
   tradeoff shape accumulates instead of evaporating.
5. **Deploy** — swap the candidate into the lower blue/green lane (§5), protecting your best owned
   rank while you keep iterating.

Skip any one and the failure shows up downstream wearing the wrong costume: a protocol mismatch looks
like a bad policy; a slot-only win looks like a champion; a noisy round looks like a regression; a
discarded failure looks like a fresh idea; a churn-rename looks like a rank drop. The discipline is
what keeps the signal honest.
