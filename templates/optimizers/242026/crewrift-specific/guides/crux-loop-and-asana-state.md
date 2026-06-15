# The crux loop and its Asana state

Reference for the 4-stage resumable improvement loop that drives crewrift policy optimization, and
for how the loop's state lives in **one** Asana project so it survives across sessions and agents.
This is the procedural backbone behind `LOOP.md` (which adds the failure-handling sub-loops,
measurement discipline, and human steers). Read this when you need to know *what a stage is*, *how
to resume by reading Asana*, *how to file a crux with the exact request JSON*, *how to link an idea
to its crux*, and *what attribution line to end every task and comment with*.

The loop is a measured, session-survivable cycle: find reproducible games where a league agent
outscores ours, analyze replays/telemetry for the behavior delta, validate ideas against the crux
without regressions, then submit and promote. Every behavioral claim is gated on an A/B at N≥30 per
arm with Wilson CIs. Refutations are first-class results — recorded with numbers so the lever is
never rebuilt.

---

## The one Asana project (where state lives)

All loop state lives in a single private Asana project so the loop resumes from documented state,
not from an agent's memory.

- **Project:** Crewrift Policy Optimization — `1215638121109109`
- **Workspace:** `1209016784099267`
- **Section — Crux Games:** `1215638525683715` (confirmed, reproducible per-seat deficits)
- **Section — Improvement Ideas:** `1215638493107848` (behavior-delta hypotheses, each linked to a crux)

Two task kinds, two sections:

- **Crux tasks** carry the verbatim reproduction config (the exact experience-request body) so
  anyone can re-spin the exact situation later.
- **Idea tasks** are dependency-linked to the crux(es) they address, and every measured result —
  including refutations — is appended as a task story. Tasks close only on validated or
  refuted-with-evidence.

> A crux is a hypothesis about the *current* policy, not a permanent record. On every policy update,
> re-run all open crux configs (Stage 3). Close the ones the update fixed.

---

## Resuming: route by what's open

Before doing anything, read the project's two sections and route by Asana state:

| Asana state | Go to |
|---|---|
| No open crux games | **Stage 1 — find** |
| Crux games without linked ideas | **Stage 2 — analyze** |
| Untested ideas | **Stage 3 — implement + validate** |
| A validated, dominant improvement | **Stage 4 — promote** |
| Stage 3 refutes an idea | record numbers, back to Stage 2/3 |
| Stage 4 promotes | loop to Stage 1 |

This routing is the whole resume protocol: the open-task shape of the two sections tells a fresh
agent exactly where the loop left off.

---

## Stage 1 — Find crux games

Goal: a significant, reproducible per-seat loss vs a named agent. Output: a task in the **Crux
Games** section.

1. **Locate the gap.** Pull standings + recent completed rounds. Find players whose per-round
   scores beat ours, and the role/division where the gap shows. Second source: if our bot uploads
   telemetry artifacts, aggregate them across past eval runs (100+ episodes query fine from
   sqlite/parquet) to find where score leaks — low-task-rate maps, kill spots, vote patterns — and
   turn the worst situations into crux candidates.
2. **Reconstruct as a seeded, reproducible request.** Build a pinned `seed` + forced imposter
   `slots` + seat-ordered roster of live pvids. Take a round we scored badly in (or a rival scored
   huge in), rebuild that round's field from its participants' current live pvids, and run us vs the
   round's top scorer in the same seat. The API does **not** expose a league round's original seed,
   so pin a fresh seed per reconstruction — the real-game FIELD is what's being reproduced, not the
   exact replay.
   - For OUR OWN past experience-request episodes the exact config including the seed **is** known.
     Any config where our arm scored low becomes a **swap tournament**: rerun it once per top player
     in our seat (requester-less arms, in parallel) and Wilson-compare each against ours. One-plus
     comparators separating above us ⇒ crux (attach a who-does-better table for the implementer).
     Nobody beating us ⇒ record "hard map, not a crux" and stop spending cycles on it.
3. **Run the counterfactual pair** on identical configs: arm A = our policy in seat k (requester);
   arm B = the better agent's live pvid in seat k (requester-less, all-opponent body). Verify seat
   assignment from `participants[].position` before trusting results — opponents land in list order,
   not by pvid uniqueness.
4. **Confirm with Wilson.** Significance is `harness_core.wilson` on paired outcomes; only
   non-overlapping CIs count. n=8 "wins" have flipped sign at n=30. If a pinned seed makes episodes
   literally identical (deterministic bots), treat that as n=1 and spread over a small set of crux
   seeds.
5. **File the crux** in the Crux Games section (search the project for duplicates first with
   `asana_search_tasks`). The task **must** contain (see "Filing a crux" below for the JSON):
   - the exact request JSON body — `seed`, `slots`, `roster`, seat, `maxTicks`
   - the original round id
   - both arms' xreq ids + replay URLs
   - measured scores (ours vs theirs, n, CI)
   - the better agent's player name + pvid

---

## Stage 2 — Analyze (improvement ideas)

Goal: behavior-delta hypotheses from replays/logs/telemetry. Output: tasks in the **Improvement
Ideas** section, dependency-linked to the crux.

1. Pick an open crux task with **no linked ideas**.
2. **Diff quantitatively first.** Pull player artifacts for every slot that uploaded one — structured
   telemetry beats eyeballing. Diff task routing/throughput, kill and vent decisions, meeting votes,
   movement. Then watch both arms' replays for the qualitative pass (hosted viewer per ereq id;
   agent-browser for captures) and pull our arm's per-agent policy logs + game logs.
   - If our bot doesn't yet upload a telemetry artifact, **that is the first improvement to ship** —
     every later crux analysis depends on it.
3. **Hypothesize the delta**, then check each hypothesis against the playbook's measured-failures
   list. Measured regressions don't get refiled — see the refuted-levers guide.
4. **File each as a task** in the Improvement Ideas section, dependency-linked to its crux task(s)
   with `asana_set_task_dependencies`. Each idea contains: observed behavior delta, mechanism,
   predicted metric effect, and an implementation sketch (`players/notsus/` in the bot repo).

---

## Stage 3 — Implement + validate

Goal: crux fixed + no backtest regression at N≥30. Output: a measured verdict on the idea task.

1. Pick one idea. **`git status` the bot repo FIRST** — a dirty tree has contaminated an A/B before
   (a dirty tree once silently bundled an imposter rewrite into a "crew-only" build). Implement,
   build `linux/amd64`, upload under a **NEW** policy name.
2. **Crux check:** rerun the crux config with the new policy in seat k — it must now match or beat
   arm B.
3. **Backtest + crux sweep:** `uv run python _harness/eval.py --candidate <new>
   --baseline <current-best> --role <crux role> --num ≥30`, and rerun **ALL** open crux configs with
   the new policy. The sweep cuts both ways:
   - a crux that still fails is the **regression guard**;
   - a crux the new policy now passes was **fixed as a side effect** — close it with the numbers and
     the fixing change noted, instead of spending a fresh Stage-2/3 cycle on it.
4. **Live-mix replica arms (mandatory before fielding).** League rounds sample the WHOLE division,
   not the top — a top-field-only ladder overweights exactly the games rounds rarely play. This is
   how a build once passed every constructed test and lost ~5 points/round live. Run paired
   candidate-vs-current arms over RANDOM fields: sample 7 distinct random live members per request
   (client-side, **without** replacement, fresh draw per 30-episode chunk, varied seeds), n≥60 per
   side pooled. The server-side `{"player": {"random": true}}` fill draws **with** replacement
   (duplicates, including your own champion) — use it only as a fallback.
5. **Record measured numbers on the idea task either way:** validated, or refuted-with-numbers. A
   refuted idea closes and loops back to Stage 2/3.

---

## Stage 4 — Promote

Goal: the experiment slot sustainably outscores the champion on mean round score. Output: a champion
swap.

**Run both player slots, always.** Live memberships rotate through the player's rounds, so two live
policies are a free live A/B at half data rate each: the **champion** (best validated) plus one
**experiment** slot carrying the latest ladder-passing candidate. Even a candidate that's only
non-inferior in constructed tests goes live, because the league mix samples configurations the
ladder doesn't. Never more than two (dilution), never a stale experiment (retire it when its
successor passes the ladder).

> "Champion" means the user's leaderboard-SCORING player slot, never winner/#1 and never a quality
> signal. The leaderboard is lifetime mean round score.

1. `uv run coworld submit <name> --league <league>` — enters Qualifiers, qualifies into the
   experiment slot; the champion is untouched.
2. Monitor both policies' clean-round means (filter collapsed rounds: skip rounds whose winner
   scored < 20) with a variance-aware comparison.
3. When the experiment sustainably outscores the champion (live-ahead **and** dominant in
   constructed tests — a windowed z-gate alone can structurally never fire, since the loser's
   in-window sample evaporates), promote with
   `POST /v2/league-policy-memberships/{lpm_id}/champion`, then retire the old champion.
4. Close the crux tasks it resolved; note the promotion on the idea task.

---

## Filing a crux — the exact request JSON

The point of the crux task is reproducibility: store the **verbatim** experience-request body so the
exact situation can be re-spun. Put the JSON in the task's plain-text notes (not html_notes).

> **API note (session-derived, unverified):** POST `/v2/experience-requests` was reworked
> 2026-06-12 to a unified `roster` body — one entry per seat with a `policy_ref` — and the old
> `requester`/`opponents` shape now 422s. If a stored crux body or a harness tool predates this,
> conform to the **deployed** server's OpenAPI spec (fetch it, don't error-probe field by field),
> verify with a 1-episode smoke, then update the JSON. The shape below is the conceptual contract;
> always reconcile against the live spec before launching.

The body that must be captured verbatim contains, at minimum:

- `game_config_overrides` with the pinned `seed`, `maxTicks`, the forced imposter `slots`, and any
  difficulty knobs used (e.g. `killCooldown`-class, or mechanic ablations like `buttonCalls: 0`).
- the seat-ordered `roster` of live pvids (one entry per seat), with our forced seat identified.
- the forced seat for the requester arm (goes in `requester.slot`, nested — not a top-level field —
  in the legacy shape).

Alongside the body, the task records: original round id; both arms' xreq ids + replay URLs; measured
scores (ours vs theirs, n, CI); and the rival's player name + pvid.

`game_config_overrides` is the experiment-control surface — it is shallow-merged and
schema-validated, so a bad key 400s. Pin the `seed` (cruxes must be reproducible); spread across a
few seeds, since two deterministic bots at one seed is a single observation.

---

## Asana mechanics

Use the Asana MCP tools, falling back to REST where noted. Base URL `https://app.asana.com/api/1.0`,
auth header `Authorization: Bearer $ASANA_PAT`.

- **Create a task:** `asana_create_task`, with the request JSON in the notes (plain-text notes, not
  html_notes — this is a known MCP quirk). `create_task` accepts `section_id` to place the task
  directly; or place it afterward with REST `POST /sections/{section_gid}/addTask`.
- **Link idea → crux:** `asana_set_task_dependencies` — the idea task depends on its crux task(s).
- **Search for duplicates** before filing: `asana_search_tasks` over the project.
- **Record a result:** append it as a task story; close the task only on validated /
  refuted-with-evidence.
- **Create a section** (if missing): REST `POST /projects/{gid}/sections`.

---

## The attribution line (end every task and comment with it)

Every Asana task and comment **ends** with the agent attribution line:

```
[Claude, acting on behalf of David Bloomin]
```

Anything externally visible beyond this private project needs explicit user confirmation.

---

## Standing rules that bind the loop

- **N≥30** for any verdict; Wilson CIs, never raw means. INCONCLUSIVE means INCONCLUSIVE — extend
  and pool, don't ship.
- **Cruxes are hypotheses about the *current* policy, not permanent records.** Every policy update
  re-runs all open crux configs (Stage 3); close the ones the update fixed.
- **Keep the telemetry artifact current:** any new decision mechanism should emit trace events in
  the player artifact, or the next crux analysis can't see it.
- **Refutations are results.** Record measured negative results with numbers (Asana story + memory
  note) so the lever is never rebuilt. A ~10:2–3 refutation-to-win ratio is normal.
- Crew correctness > imposter cleverness (6 of 8 seats are crew; crew games are task-decided — task
  throughput beats vote logic).
- The league scheduler can stall; a frozen ladder is not a regression.
- League-visible actions (submit, retire, champion swap, external bug filing) are gated on explicit
  user approval and done only by the lead agent, never a subagent.
- If `coworld upload-policy` fails on the ECR push, use the manual `authorization_token` path.

---

## Quick reference

| Stage | Goal | Output | Asana section |
|---|---|---|---|
| 1 find | significant, reproducible per-seat loss vs a named agent | crux task with verbatim request JSON | Crux Games |
| 2 analyze | behavior-delta hypotheses from replays/logs/telemetry | idea tasks linked to crux | Improvement Ideas |
| 3 validate | crux fixed + no backtest regression at N≥30 | measured verdict on the idea | Improvement Ideas (story) |
| 4 promote | experiment > champion on mean round score | champion swap | close crux + note on idea |

## Related tooling

`_harness/eval.py` + `_harness/league_eval.py` (league A/B), `_harness/antfarm_run.py` (raw
experience requests + artifact download), `_harness/league_roster.py` (live roster),
`_harness/dashboard.py` (UI over the same A/B runs), Asana MCP tools / REST, agent-browser (replay
watching). See `LOOP.md` for the full operational narrative, failure-handling sub-loops, and
measurement discipline; see the refuted-levers guide for levers that are measured-dead and must not
be rebuilt.
