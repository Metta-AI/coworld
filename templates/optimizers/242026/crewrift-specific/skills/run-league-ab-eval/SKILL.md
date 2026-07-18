---
name: run-league-ab-eval
description: Use when running a hosted Crewrift policy A/B and judging it with Wilson confidence intervals.
---

# Run a league A/B eval (candidate vs baseline)

The crewrift eval runs **server-side on Observatory**, NOT in local docker.
Each arm is one `POST /v2/experience-requests`: the tested policy occupies a
single forced-role seat and the league's top players fill the other 7 seats; the
games run on k8s. There is no local A/B, no Aurora/EC2 runner queue, no docker
scrimmage — those are deleted. Competitors' policy images are private (the
round/leaderboard API exposes only a `policy_version_id`, never an image), so
only the server can run them against you.

The engine is **`league_eval.py`** (`run_league_ab`); the CLI front door is
**`eval.py`**. Both live in `_harness/` in the crewrift repo (the universal copies
in this package are `tools/league_eval.py` and `tools/eval.py`).

---

## Preconditions (do these first, every time)

1. **Both candidate and baseline must be uploaded, OWNED policies** resolved by
   name. The CLI resolves names via the coworld API; a name that isn't an owned,
   uploaded policy fails before any submit (there is no server cancel API, so a
   bad name MUST fail early). Upload with:
   ```
   coworld upload-policy <image> --name <name>
   ```
   (Note: current `coworld upload-policy` consumes the server's ECR
   `authorization_token` response. If an older pinned install fails before
   upload, upgrade first; use the manual fallback in `build-and-upload-policy`
   only if upgrade is impossible.)

2. **Confirm the two arms are actually different builds** before launching. A
   prior run silently A/B'd a policy against ITSELF and produced a meaningless
   verdict. Docker buildx content-addresses images:
   - Check the two arms' image IDs DIFFER (`docker image inspect <img> --format '{{.Id}}'`).
   - Build the baseline from the **same tree minus only the change under test**
     (`git stash` → build → `git stash pop`, or back up the file, revert the
     specific edits in place, build, restore). Do NOT reuse a days-old image as
     baseline — that confounds the comparison with every other drift. This repo
     got burned by a dirty tree bundling an unrelated imposter rewrite into a
     "crew-only" measurement, so **`git status` the bot repo before committing or
     building.** (session-derived, unverified)
   - After an intended change, confirm the image ID CHANGED before testing — an
     unchanged ID means the change never reached the artifact. After a revert,
     if the rebuilt ID equals a previously-validated-good build's ID, the revert
     is provably byte-identical and needs no re-scrimmage. (session-derived, unverified)
   - With a main repo + Claude worktrees, an edit can land in the worktree copy
     while builds/runs execute from the main copy — verify which tree you're
     editing vs running from. (session-derived, unverified)

---

## Standard path: the `eval.py` CLI

This is the canonical "did my change help?" command. Run a dry-run first to
print the seat plan and roster without submitting, then the real run.

```
# Dry-run: resolve roster + seat, print the plan, submit nothing.
python eval.py \
  --candidate <candidate-name:vN> \
  --baseline  <baseline-name:vN> \
  --role crew \
  --num 30 \
  --dry-run

# Real run.
python eval.py \
  --candidate <candidate-name:vN> \
  --baseline  <baseline-name:vN> \
  --role crew \
  --num 30
```

CLI flags (defaults shown):

| flag | default | meaning |
| --- | --- | --- |
| `--candidate` | required | candidate policy name/label (owned, uploaded) |
| `--baseline` | required | baseline policy name/label (owned, uploaded) |
| `--role` | `crew` | `crew` or `imposter` — the forced role of the tested seat |
| `--num` | `8` | paired episodes per arm. Cap **100**. Use **30** for a real verdict (see below) |
| `--top-n` | `7` | distinct top league players filling the other seats |
| `--maxticks` | `10000` | league-realistic length; an episode runs `maxticks/24` seconds of wall time |
| `--league` | Crewrift league (hardcoded) | `league_605ff338-0a2e-4e62-aeda-559df9a9198f` |
| `--division` | `None` | division id |
| `--opponent` | (none) | explicit opponent `player_name` or **live** `policy_version_id`, repeatable, seat order; overrides ranking |
| `--backend` | `k8s` | `k8s` = league runner (any league policy); `antfarm` = staging fleet (antfarm-registered only) |
| `--notes` | `eval.py` | free-text label on the request |
| `--dry-run` | off | resolve roster + print plan without submitting |

**Pick `--num` for the CI you need, not for wall-clock.** Episodes within an arm
run **fully parallel** server-side and both arms now run **concurrently** (a
2-worker thread pool, commit 6be96c2). A/B wall-clock is roughly **one arm**:
~7-8 min at `maxticks=10000`. The server is NOT the bottleneck (~240 warm-episode
capacity, `MAX_OUTSTANDING_JOBS=2000`, no per-user/per-league quotas; even
`num=30 × 2 arms = 540 pods ≈ 195 vCPU` fits the warm pool). The only floor is
realtime sim pacing (`maxticks/24` s per episode). So raising `num` 8→30 tightens
the Wilson CIs at ~zero extra wall-clock cost — **default to `--num 30`.**

The CLI prints, per arm: win count / n, Wilson 95% CI, mean seat score, total
kills, total vote_timeouts, the two experience-request ids, and a `verdict`
string derived from whether the win-rate CIs separate.

---

## Crux / swap arm: drive the raw `roster` API

For a crux arm (one comparator's bot in YOUR seat) or any non-paired layout that
the CLI doesn't express, build the request body directly. The
`POST /v2/experience-requests` body was **reworked server-side on 2026-06-12** to
a unified `roster` array. The **old `requester`/`requester_slot`/`opponents`/
`rotate_seats` shape now returns 422** (`"roster" Field required`).

Server: `https://softmax.com/api/observatory`. New body — one
`V2RosterParticipant` per seat:

```json
{
  "target": {
    "league_id": "league_605ff338-0a2e-4e62-aeda-559df9a9198f",
    "division_id": null, "coworld_id": null, "variant_id": null,
    "league_name": null, "division_name": null
  },
  "roster": [
    {"player": {"policy_ref": "daveey-notsus-tier5c:v1"}, "slot": 0},
    {"player": {"policy_ref": "<raw pvid uuid>"}, "slot": 1},
    {"player": {"top_n": 7}},
    {"player": {"random": true}}
  ],
  "num_episodes": 30,
  "execution_backend": "k8s",
  "game_config_overrides": {
    "maxTicks": 10000, "seed": 679961,
    "imposterCount": 2, "autoImposterCount": false,
    "slots": [{"role": "crew"}]
  },
  "notes": "crux <id> arm A"
}
```

Rules the API enforces:
- Each roster entry's `player` is **exactly ONE of** three keys:
  - `policy_ref` — a label `name:vN` **OR** a raw `policy_version_id` UUID. Must
    be an owned policy or a **live** league member. **Stale pvids from old round
    results are rejected** ("did not match an active runnable policy").
  - `top_n` — draw from the target division's top-N champions (Competition pool).
  - `random` — draw a random live member.
- `slot` pins a seat. `slot: -1` or omitting `slot` = round-robin into open slots.
- `num_episodes` ≤ 100.
- **No requester/opponents distinction.** The counterfactual "their bot in our
  seat" arm is a first-class roster entry: put the rival's pvid at the seat you
  want and put your policy nowhere. This is what makes the swap-tournament cheap.
- Forced roles go in `game_config_overrides.slots` (per-seat `{"role": "crew"|"imposter"}`),
  with `imposterCount`/`autoImposterCount`. Forced slots are confirmed accepted
  by the live server; a future rejection is a HARD failure (no seed fallback).

**The roster source must be LIVE members, not stale pvids.** Get each top
player's current live pvid from the live-membership list ranked by recent round
score — the harness does this via `league_roster.fetch_top_players` /
`live_members(league_id, division_id, active_only=True)`. A bare `player_name`
with >1 live version is ambiguous and rejected; a `policy_version_id` lifted from
an old round result is un-runnable. The league **churns versions mid-session**
(e.g. crewborg v19→v21→v22 in one day) — re-fetch live members and validate every
pvid right before each launch.

---

## Polling to completion

Poll `GET /v2/experience-requests/{xid}` until the top-level `status` AND **every**
`episodes[].status` are in `{completed, failed, cancelled}`. Poll cadence ~10s.
Early `404`/`425`/`429`/`5xx` are **transient — keep polling, do not fail.**

Timeout budget (the formula `league_eval` uses — do not use a fixed short
timeout, it falsely fails slow-but-healthy episodes):
- **Total arm budget:** `~ num * maxticks/24 * 3 + 900` seconds.
- **Wedged-participant detection:** if ZERO episodes complete within
  `maxticks/24*3 + 600` seconds, a participant is wedged — **fail LOUD.**

**Wedged-participant stall (real failure mode).** If ANY of the 8 player
containers hangs (never connects, or hangs in crewrift's lockstep), the whole
episode freezes at tick 0 and never completes; the request sits `running` forever
(no cancel API → it orphans). Signature: all per-episode statuses `running`,
0 completed, and the live spectator ws renders a byte-identical looping (frozen)
scene. This is DISTINCT from cold-start: a big submit normally spends its first
~2-4 min all-`pending`/`submitted` (dispatch fan-out + Karpenter node spin-up)
before "running" climbs — that is normal, not a stall. Localize a bad bot by
bisecting at a SHORT `maxticks` (1000 ≈ 42s/ep): swap a known-good candidate
against the same opponents; if it completes, the original candidate is the hanger.
Lowering `maxticks` does NOT fix a wedge (it's a connect/start hang,
length-independent). The harness `run_arm` fail-fasts at the stall grace and the
dashboard has a per-row terminate button.

**Run the poll from a Monitor / persistent poller, not a backgrounded Bash shell
with a long foreground `sleep`** — detached background pollers have died silently
mid-sleep (arms completed server-side but the logfile stayed 0-byte with no
verdict). (session-derived, unverified)

---

## VERIFY THE SEATING before trusting any result

Slot assignment is **not guaranteed** to match request order for `slot: -1` /
omitted entries. **Always confirm who actually landed where** from
`episodes[].participants[].position` + `policy_version_id` before reading the
verdict. Two specific traps:
- Swap comparators that are ALSO in the top-7 field can't be seat-verified by a
  unique pvid (the same pvid appears twice) — verify by **position**.
- Opponents from a list land in **list order** — verify by position, not identity.

Also sanity-check what you measured matches what you intended: forced role
(`game_config_overrides.slots`), and — if the policy carries an LLM advisor — that
the advisor actually fired (vote-accuracy / fire-rate via `metrics.py`), since
there is no eval-time bedrock flag; behavior is whatever the uploaded image carries.

---

## Reading the verdict

- The leaderboard metric is **mean round score** (a multi-episode mixed-role
  average), NOT raw win rate. A forced-top-7 A/B **isolates a single change** but
  does NOT linearly predict league rank — treat it as "did this edit help in a
  faithful field," not "this is my new rank."
- "**champion**" is a membership label = a user's leaderboard-SCORING slot (each
  user has 2 players: experiment + champion). It is NOT winner / #1. Judge success
  by **mean seat score / win rate vs the field**, never the `champion` label.
- A real but small deficit often only clears Wilson at n=30, and sometimes only
  after **pooling the same-direction deficit across related configs** (single
  configs overlap at n=30; pooling separates them).

---

## Success check

You have a trustworthy verdict when ALL of:
1. The two arms were provably different builds (image IDs differed) and the
   baseline was the same tree minus only the change under test.
2. Both arms reached terminal status: top-level + every episode in
   `{completed, failed, cancelled}`, with no wedged-participant stall (no arm sat
   `running` with 0 completed past the stall grace).
3. Seating was verified from `episodes[].participants[].position` — the tested
   policy was in the intended forced-role seat in BOTH arms, and any duplicate
   comparator was disambiguated by position.
4. `--num` was large enough (default 30) that the Wilson CIs are tight enough to
   either separate or to call the change neutral.
5. The CLI printed (or your raw run computed) both arms' win/n + Wilson 95% CI,
   mean seat score, kills, vote_timeouts, and the two experience-request ids — and
   the `verdict` reflects whether the win-rate CIs separate.

If any of these fail, the verdict is not trustworthy — re-run, don't ship the edit.
