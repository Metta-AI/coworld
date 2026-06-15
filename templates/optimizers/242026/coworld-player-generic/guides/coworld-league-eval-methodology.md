# Coworld league eval methodology (game-agnostic)

How to measure whether a change to your player helped, in any Softmax coworld league. This is the
**methodology** — the shapes, invariants, and traps — not a command reference. The exact endpoints,
body schema fields, league/division identifiers, and CLI invocations live in the **project tier**;
fetch them from there (and re-confirm against the deployed server's schema, which drifts). The pure
statistics — confidence-interval verdicts, minimum-n, pooling, extend-don't-re-roll — live in the
**generic tier** and are referenced, not restated, here.

Read this when you need to know: why the eval is server-side, how a forced-role paired A/B is
constructed, how to find and confirm a crux, how the promotion gates compose, why the roster must be
re-resolved every launch, and what to do when the coworld version rolls.

---

## Why server-side, and what that forces

Competitor policies are **private images** the league server holds and runs by reference. You cannot
pull them and you cannot run them locally. The only faithful measurement is therefore a **server-side
counterfactual match**: the server seats your policy reference in one seat and real opponents in the
others, runs the game on shared infrastructure, and returns per-seat results plus replays/artifacts.

This single fact drives the whole methodology:

- **The candidate and the baseline must both be uploaded, owned policy references** — not local
  container tags. A "compare my two local builds" instinct does not work here.
- **A local run is a mechanism check only** (does the bot connect, does a new code path fire, does the
  advisor/subprocess come alive). It can never measure strength against a field it cannot instantiate.
  Keep a local lab for cheap pre-flight, but never let it stand in for a league verdict.
- **The request body is your entire experiment-control surface.** Difficulty knobs, seeds, role
  forcing, mechanic ablations — all of it goes in the per-match config the server accepts, not in
  infrastructure you build around it. (A previous generation of this work built a whole runner fleet
  to do what the server's match-request API does for free; don't rebuild that.)

---

## The paired forced-role A/B

The standard "did my change help?" test is two arms on **identical** field and seed, with only the
thing-under-test swapped:

- **Arm A** — your candidate policy pinned into one **forced-role seat**, the rest of the seats filled
  by a chosen field (the live top-N, or an explicit roster of live references).
- **Arm B** — the baseline (the current incumbent, or, for a crux, the rival's live policy reference)
  in the *same* forced seat, same field, same seed.

Invariants that make the comparison honest:

- **Force the role explicitly, and fail loud if the server rejects it.** Role forcing belongs in the
  match config's role/slot layout, set so the candidate's seat is the role under test. The banned
  anti-pattern is a fallback that assigns roles some other way (e.g. from the seed) and post-filters —
  that silently changes *which role you measured*. A rejection is a designed hard failure; surface the
  validator message and stop.
- **Pin the seed.** Most coworlds expose a seed in the match config that makes the map, tasks, and any
  role draw deterministic — this is the lever that makes a crux reproducible. **Caveat:** two
  deterministic bots at one fixed seed produce *one* observation, not n; spread a crux across a small
  set of seeds.
- **Verify who actually landed where.** Unpinned or list-order fills are **not** guaranteed to seat by
  reference — read each episode's participant positions and confirm the candidate (and each opponent)
  is in the seat you intended **before** trusting the result.
- **Run the two arms concurrently.** Episodes parallelize fully server-side; the floor is realtime sim
  pacing plus provisioning, not server capacity. Pre-resolve all references before submitting either
  arm (there is typically no server-side cancel — a late name-resolution failure orphans a full run),
  and share an abort signal across both arms.
- **Scale the poll timeout from `num × match-length`, never a flat constant.** Zero episodes completing
  past a single-episode budget means a **wedged participant** (a never-connecting bot can freeze a
  tick-based connect timeout at tick 0 forever) — fail loud on a stall-grace budget. A poller crash is
  **not** a backend failure: re-fetch the existing request id, never resubmit.

The verdict is computed from each episode's per-seat result record using the generic tier's CI math.
Verdict only on **non-overlapping** intervals; INCONCLUSIVE means extend on the *identical* config and
pool, per the generic tier — do not re-roll the field.

---

## Finding and confirming a crux

A **crux** is a confirmed, reproducible per-seat deficit: a complete match-request body (pinned seed +
forced role layout + seat-ordered roster of live references) stored verbatim so anyone can re-spin the
exact situation. It is a hypothesis about the **current** policy, not a permanent fact. Sources, in
the order they tend to pay off:

1. **Standings deltas.** Which live players beat you, by how much, in which role/division, over a wide
   round window. Re-rank before every batch — the board churns within hours.
2. **Round reconstruction.** Every "we scored lower in that round" observation needs an n≥(floor)
   reconstruction before it becomes a crux; most single-round deficits dissolve as role/seat/draw
   noise. The league rarely exposes a past round's original seed, so pin a *fresh* seed and reproduce
   the round's **field** (rebuild it from its participants' current live references), not the exact
   replay.
3. **Swap tournaments on your own past episodes.** For your *own* past match requests you hold the
   exact seed and config. Any config where your arm scored low becomes a swap tournament: rerun that
   precise setting once per top player swapped into your seat (opponent-only arms, in parallel) and
   CI-compare each against yours. One or more comparators separating *above* you ⇒ crux (attach a
   who-does-better table for the implementer). Nobody beating you ⇒ record "hard config, not a crux"
   and stop spending cycles on it.
4. **Counterfactual "their bot in our seat."** Arm A = your policy in seat k; arm B = the rival's live
   policy reference in the *same* seat. Because competitor images are private, this server-side swap is
   the only faithful "are they actually better here" comparison.
5. **Rival mining.** Read public rival source where it exists; pull any **team-readable per-slot
   telemetry artifact** a rival uploads (in this league family, *any* uploading slot's artifact is
   readable from your own requests, including a competitor's) and the rival's per-agent logs from your
   B-arms; decode replays for ground truth (below). Mining beats inference.
6. **The user's own replay-watching.** Human-observed levers are valuable **hypotheses** — take them,
   then measure; never ship them unmeasured.

**On every policy update, re-run ALL open cruxes.** Still-failing cruxes are the regression guard; a
crux the new policy now passes is closed as fixed-by-side-effect *with numbers*, instead of spending a
fresh analysis cycle on it.

---

## Ground truth: don't trust telemetry over the replay

When a verdict needs explaining or seems impossible, escalate through artifacts rather than reasoning
from the summary numbers:

1. **Per-agent policy logs** — grep the decision strings to confirm a mechanism actually fired (a
   summary field showing "no timeouts" does **not** prove a subprocess advisor was alive; the
   dead-process signature is visible only in the agent log). When a grep count looks impossible, read
   the raw lines — the regex may not match the live log format. Ground every parser in
   **current-format** artifacts pulled from a live run, never a stale sample.
2. **Replay decoding — the authoritative oracle.** Re-simulate the recorded replay to reconstruct
   per-seat deaths/movement/outcomes; this is the truth that telemetry approximates. A "hash mismatch
   at tick N" warning does **not** invalidate the reconstruction — validate by exact match of final
   per-seat roles/rewards/outcomes against the recorded scores. (The project tier names the decode
   tool.)
3. **Rival telemetry** — the team-readable artifacts and B-arm logs from #5 above.
4. **Config-ablation probes** — disable a suspected mechanic in the match config for *both* bots and
   re-run paired arms; the cleanest way to attribute an edge to a single mechanic.

---

## The promotion gates (how they compose)

Promotion is the final, league-visible step — gated on explicit user approval. Escalate a candidate
through these rungs, each gating the next, before it can replace the incumbent:

1. **Crux config at multiple seeds** — beat the comparator with non-overlapping intervals.
2. **Opposite-role regression check** — a fix to one role must not tank the role you also fill.
3. **Same-era field control** — re-run the incumbent on the *current* field before declaring any
   regression; baselines rot within hours.
4. **Constructed league A/B** vs the incumbent on the top field.
5. **Live-mix replica arms (binding gate).** Randomized division-mix fields: sample N distinct live
   members **client-side without replacement**, fresh draw per chunk, varied seeds, pooled to adequate
   n per side. A server-side "fill with a random member" option typically draws **with** replacement
   (duplicates, possibly including your own labelled slot) — use it only as a fallback. This gate
   exists because a candidate can pass every constructed top-field A/B and still lose points live.

Then, with approval:

- **Submitting** enters the policy as the experiment slot; it does **not** auto-displace the labelled
  slot. Run the two-slot live A/B (see AGENTS.md): labelled slot + one experiment, never three, never
  a stale experiment.
- **Promote only on the totality of evidence** — live-ahead over a wide window **and**
  constructed-dominant. A windowed significance gate alone can structurally never fire (the loser's
  in-window sample evaporates as rounds rotate to the leader).
- **Retire stale roster policies first.** The league rotates rounds among **all** your live
  memberships, so an ancient low-mean policy mechanically drags your blended leaderboard mean — pruning
  is often the cheapest gain available.
- **After ANY membership churn, re-verify the labelled-slot flag and the leaderboard entry.** Churn
  silently clears the flag and delists the player; the list endpoint reads a lagging replica, so
  confirm against authoritative state.

---

## Re-resolve the roster every launch

The league rolls policy **versions** mid-session. Opponents must be **live memberships** — competing,
container-ready. Stale references pulled from old round results are rejected; player *names* are
ambiguous and also rejected at submit. So, immediately before **every** launch:

- Re-fetch the live membership list and resolve your field **by player name → current live
  reference**. Validate every reference right before submit.
- **Resolve all references before submitting any arm.** A late failure orphans a full run.
- Opponents may land in **list order**, not by reference uniqueness — pin seats where you can and
  verify positions where you can't.
- Pooling across chunks is valid **only** when the field references are byte-identical across the
  pool; a mid-batch version roll breaks the pool.

---

## When the coworld package rolls

The league can bump its coworld package **without notice**, after which every local artifact — the
vendored game source, your harness defaults, your built images — silently targets a dead version, and
commands that *look* like they work certify against a game the league no longer runs. The migration is
a once-per-roll procedure, run end-to-end before trusting a single local number:

1. **Detect the live-vs-local mismatch** — ask the live league what coworld version it runs and
   compare against what local state references. If they differ, nothing local is trustworthy yet:
   re-download the package and run one baseline before believing any measurement.
2. **Back up the crown jewels first.** Your highest-value work (strategy patches, an untracked
   advisor, a custom build file) often sits **uncommitted and untracked** inside the vendored game
   repo, where reconciliation can clobber it. Save tracked changes to a patch and copy untracked files
   out *before* any checkout/reset/merge. `git fetch` is safe (it doesn't touch the tree) — fetch to
   assess the delta while your work is intact.
3. **Triage old patches against the (often rewritten) upstream**, per patch: **absorbed** (upstream
   now does it — drop), **known-dead** (a measured regression — do not carry), **carry** (a real
   un-absorbed win). Never blind-`git apply` — that re-introduces dead levers and fights changes
   upstream already made.
4. **Verify the scoring constants survive.** Diff the reward/scoring constants across versions. If
   **unchanged**, every prior strategic conclusion holds and the migration is pure re-wiring. If
   **changed**, the playbook needs **re-derivation**, not re-wiring — your measured win/loss and
   refuted-lever conclusions are now suspect.
5. **Run the cheap compat probe before rebuilding** — one OLD image against the NEW game's fixture. A
   clean connect/run/replay means the protocol is backward-compatible and your images are still usable;
   a failure means a rebuild is mandatory, learned from one probe instead of a full round trip.
6. **Port carried patches by symbol-grep**, not merge guesswork — grep the new source for every
   symbol the patch references (plus a name-collision check) before editing. If every symbol still
   exists with the same signature the port is mechanical; if one moved, the grep surfaces it before you
   compile.
7. **Resolve player identity from the manifest id, not a binary's self-reported log name** — they can
   disagree, and the manifest is authoritative. This compounds the seat-verification rule: a bot's log
   name is not its identity.

(The project tier carries the exact commands and the specific source-file paths for steps 1, 4, and 6,
and the named record of which patches were absorbed/known-dead/carried in past rolls.)

---

## Related

- `coworld-optimization-loop.md` — the loop this methodology sits inside.
- `cross-coworld-craft.md` — the standing cross-league craft (protocol-family matching, the full
  role/slot gate, terminal-evidence discipline, named negative controls, blue/green lanes) that this
  guide assumes and does not restate.
- The **generic tier** — the statistics (CI verdicts, power, pooling) and the fail-loud /
  root-cause principles this guide applies.
- The **project tier** — the concrete endpoints, IDs, body schema, decode tool, source paths, and
  commands.
