# The coworld player-optimization loop (shape)

The end-to-end cycle for improving a player against a live coworld league, written as a **shape** —
the stages, what each one guards, and where the failure-handling sub-loops attach. It carries **no
commands**; the concrete invocations (how to read standings, build the image, submit the A/B, decode a
replay) live in the **project tier's** loop and skills. The eval mechanics each stage invokes are in
`coworld-league-eval-methodology.md`; the statistics and the fail-loud/root-cause discipline are in
the **generic tier**. This guide is the spine that orders them.

A coworld league is an **adversarial, mixed-role, lagging-signal** system. Every stage below exists to
stop a specific way of fooling yourself; skip one and the failure reappears downstream wearing a
different costume.

---

## The cycle

```
        ┌─────────────────────────────────────────────────────────────────────┐
        │                                                                     │
        ▼                                                                     │
 [0] ORIENT ──► [1] PICK LEVER ──► [2] ROOT-CAUSE ──► [3] EDIT THE BOT        │
 (refresh live   (crux from         (read game +       (one variant = one     │
  league state,   standings/replay/   bot source +      diff; validation      │
  roster, your    rival mining/       artifacts BEFORE  ladder, cheapest      │
  own state)      user observation)   coding)           rung first)           │
        ▲                                                      │              │
        │                                                      ▼              │
        │                                          [4] BUILD + UPLOAD POLICY  │
        │                                          (target arch; new name;    │
        │                                           confirm image changed)    │
        │                                                      │              │
   [7] RECORD ◄── [6] SHIP or REFUTE ◄────────────── [5] SERVER-SIDE PAIRED   │
   (durable note,  (validation ladder, gated          A/B + DECODE GROUND ────┘
    tracker story,  submit/promote, two-slot           TRUTH (CI verdict;
    refutations     live A/B, totality-of-evidence     replay oracle explains
    too)            promotion)                          the verdict)
```

One full cycle (edit → build → upload → paired A/B at the minimum n per arm → verdict) is bounded by
realtime sim pacing plus provisioning, not by server capacity — so **run multiple cycles in
parallel**. Idling on a poller when early points already bound the answer is wasted time: fire the
next experiment at the estimated optimum instead of waiting for stragglers.

---

## [0] Orient — refresh live state before trusting anything local

Nothing local is trustworthy until you've reconciled it against the live league this session:

- **Check the live coworld version against what local state references.** If it rolled, run the
  version-roll migration (see `coworld-league-eval-methodology.md`) before believing any local number.
- **Read your durable memory and the project playbook**, and check the recorded refuted-levers list
  *before* re-implementing anything — memory supersedes stale playbook sections.
- **`git status` the bot source.** A dirty tree silently bundles an unrelated change into a build and
  invalidates the A/B; know exactly what each image is built from. (The bot source may live in a
  separate nested repo — the project tier says where.)
- **Pull current standings from the official ranking** (the slow lifetime mean), not an ad-hoc
  per-policy aggregation. Remember the leaderboard-slot label is not a quality signal.
- **Check for already-completed runs of the pairing you care about** — fresh artifacts from a prior
  session are free episodes to mine.
- **After any restart, audit background state** — list lane workdirs by newest file, read each lane's
  checkpoint, stop duplicate monitors, respawn dead lanes (background agents do not survive restarts).

## [1] Pick the lever — generate a crux

Turn "we're behind here" into a **confirmed, reproducible per-seat deficit** stored verbatim so it can
be re-spun. The sources and confirmation method are in `coworld-league-eval-methodology.md` (standings
deltas, round reconstruction, swap tournaments, the counterfactual swap, rival mining, user
observation). Maintain loop state in **one** durable tracker with two kinds of item — crux configs and
improvement ideas, each idea dependency-linked to the crux it addresses — so a fresh agent resumes by
reading the tracker, not an agent's memory. **On every policy update, re-run all open cruxes.**

## [2] Root-cause before implementing

Do **not** code from the hypothesis. First:

- **Read the actual game source** (win conditions, the mechanics you're touching) and your bot's own
  decision path — targeted search, not whole-file reads. Verify empirically where the source is
  ambiguous; a second code path can invalidate a source-only conclusion.
- **Check what your bot already implements** before porting anything (see AGENTS.md's
  verify-before-porting rule).
- **Check whether the trigger is even arithmetically reachable.** A behavior that never fires is often
  gated on a threshold the evidence can never sum to — audit the trigger's math against the maximum
  attainable evidence before tuning. (This is the single highest-leverage root-cause move in this
  family of bots.)
- **Confirm the metric can move at all** (instrument calibration — see AGENTS.md) and that any
  subprocess/advisor path is actually alive before attributing behavior to logic.
- When a copied behavior fails, **descend one causal layer and re-measure**, rather than re-tuning the
  same layer.

## [3] Edit the bot

- **One variant = one branch/worktree = one diff**, so each built image maps to exactly one change.
  Name variants in a ladder and validate each dial separately so contributions are measured, not
  guessed.
- **Validation ladder, cheapest rung gates the next** — static/semantic check first, a fast native
  compile next, the expensive cross-arch image build last. (The project tier names the exact check
  commands and the headless-build defines that matter.)
- **For deletions**, search every identifier of the removed feature, read each touchpoint, and check
  whether a helper is shared before removing it; re-search for zero dangling references after.
- **Construct the baseline as the same tree minus only the change** — build the candidate, revert
  in-place, build the baseline with identical flags, restore; confirm the two image IDs differ. Never
  reuse a days-old image as a baseline.
- **New decision mechanisms must emit trace/telemetry** into the player artifact, or the next crux
  analysis can't see them.

## [4] Build and upload the policy

- Build for the **arch the league runs** (often via emulation on your machine); run the build in the
  background with a log file. After an intended change, confirm the image **changed**; an image
  identical to a prior verified-good build proves byte-identical behavior (skip re-validation). A
  compile error whose line doesn't match the current file means a stale build-context layer — rebuild
  without cache.
- Bake any required runtime env (model ids, credentials flags) into the image and verify it; a
  default that the runner account can't honor dies **silently**.
- **Upload as a NEW policy reference.** If the upload CLI is broken (it has been), use the manual
  registry-push path. Re-uploading an identical image may report "already pushed" — that is not an
  error; an aliased policy (same image, new name) registers without a rebuild. (The project tier has
  the exact upload steps.)

## [5] Server-side paired A/B + decode ground truth

Run the paired forced-role A/B (`coworld-league-eval-methodology.md`): candidate vs baseline, same
field and seed, candidate in the forced role seat, opponents in the rest, **both arms concurrent**,
both references resolved before either submit. Read the verdict from per-seat results with the generic
tier's CI math — verdict only on non-overlapping intervals; INCONCLUSIVE means extend and pool on the
*identical* config, never re-roll.

When the verdict needs explaining or seems impossible, **go to ground truth** in order: per-agent
logs → the replay oracle → rival telemetry → config-ablation probes. Calibrate the instrument before
trusting it — a metric pinned at a structural floor/ceiling measures nothing.

Launch long runs as tracked background jobs (unbuffered, to a log file) and watch them with a
**persistent monitor poller**, never a detached shell with a foreground sleep (those die silently
mid-poll). Pollers must tolerate transient post-create errors and read-timeouts on the heavy detail
fetch; still fail loud at zero completed episodes.

## [6] Ship or refute

Escalate a winning candidate through the promotion ladder (`coworld-league-eval-methodology.md`): crux
at multiple seeds → opposite-role regression check → same-era field control → constructed league A/B →
**live-mix replica arms** (the binding gate). Then, **with explicit user approval**, submit into the
experiment slot and run the two-slot live A/B; promote only on the **totality of evidence** (live-ahead
over a wide window **and** constructed-dominant), never on a single windowed gate. Retire stale roster
policies first; after any churn, re-verify the labelled-slot flag and the board entry.

A **refutation is a result** (generic tier) — record it with numbers and loop back to [1]/[2]. A
~10:2–3 refutation-to-win ratio is normal; the recorded negative is what stops the lever being
rebuilt.

## [7] Record, then loop

- Write a durable memory note (one fact per note) for **every** measured result, *including
  refutations*, in the same session it lands. **Correct or delete** a note in place the moment new
  evidence overturns it.
- Append the numbers to the tracker item as a story; close the item only on
  validated/refuted-with-evidence.
- Commit any process/method change to the project's docs so the loop survives sessions.
- Update the comparison baseline to the newest shipped policy and **re-run all open cruxes** ([1]).

---

## Standing ground rules (enforced throughout)

These are the coworld-specific operating rules; the underlying *principles* (never ship on a vibe,
refutations are results, fail loud, fix the root cause) are stated in the generic tier and not
repeated here.

- **If no matches are in flight, the loop is stalled** — keep probes or extensions running and a
  liveness monitor up (fresh local analysis files count as liveness too).
- **Don't idle on pollers** when early points already bound the answer — fire the next experiment in
  parallel.
- **League-visible actions are gated on explicit user approval** and done only by the lead agent,
  never a subagent — and audit the **full** roster, not a name-filtered view.
- **Re-resolve live state every launch; every verdict is a within-battery paired comparison** against
  a same-era control.

## Failure-handling sub-loops (standard moves, not surprises)

- **Wedged match (0 complete, stuck "running").** Distinguish hung from slow — a byte-identical
  spectator frame sequence seconds apart is a frozen sim. A tick-based connect timeout means one
  never-connecting participant freezes the game at tick 0 forever; bisect by swapping a known-good
  policy into the exact field. Add a stall-grace fail-fast to pollers.
- **Server API changed under you (a previously-working body now rejected).** Do **not** error-probe
  field by field — fetch the deployed server's schema, conform to **it** (your local checkout can be
  ahead of or behind prod), verify with a one-episode smoke, then update the project's API doc and tell
  every agent using the old shape.
- **Backend outage triage.** Before concluding anything, run two controls: a known-good simple match
  on the same backend (backend-wide vs game-specific) and the same roster on an alternate backend if
  one exists. A worker GET returning 200 proves HTTP liveness, not that match-start works. File a real
  backend failure with evidence (gated on approval) and arm an event-driven recovery watch; a large
  pending count can be a healthy conveyor — measure drain rate before scaling anything.
- **Background process death.** Detached pollers and subagent lanes die silently across restarts. Use
  tracked background jobs or persistent monitor loops; every lane checkpoints its state to a file so a
  relay agent resumes losslessly; audit any lane silent too long via workdir file timestamps.
- **The bot plays "dead" (an advisor/subprocess silently not firing).** Check in order: is the
  enabling flag actually wired; is the configured model/credential invokable from the *execution*
  account (a default that works locally can be disabled there); is concurrency degrading it (run
  advisor-sensitive evals at low concurrency). Synthetic burst probes do **not** reproduce sustained
  in-game load failures. A local realtime run can validate that the mechanism *fires*, never its
  competitive efficacy.
- **Local smoke false alarms.** Cross-arch-under-emulation bots drop sockets (false "crash"); a short
  fixture can legitimately score all zeros — read the game's own stdout for connect/start/replay before
  concluding anything is broken.

---

## Related

- `coworld-league-eval-methodology.md` — the eval mechanics each stage invokes.
- `cross-coworld-craft.md` — the cross-league craft (protocol-family, full role/slot gate, terminal
  evidence, named negative controls, blue/green lanes) assumed throughout.
- The **generic tier** — the statistics and the fail-loud / root-cause / refutations-are-results
  principles this loop applies.
- The **project tier's** loop and skills — every concrete command this shape leaves blank.
