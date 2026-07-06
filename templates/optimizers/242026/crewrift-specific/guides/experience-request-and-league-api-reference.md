# Experience-Request and League API Reference (Crewrift / Observatory)

This is the lookup the eval skills point into for exact shapes. It is a **reference**, not a recipe:
read it when you need the precise auth handshake, the post-2026-06-12 roster body schema, a constant,
an artifact route, the timeout formula, or the player-artifact upload/download contract. For the
end-to-end loop (when to launch, how to read a verdict, the validation ladder), see `../LOOP.md`.

Everything here is the **server-side Observatory experience-request engine**: the candidate occupies a
single seat, the league's strong/varied field fills the rest, and the game runs on shared k8s. This
replaced both the local docker A/B and the Aurora/EC2 runner queue, because neither reproduced how the
league actually scores a policy (one seat against a real field). Competitor images are private ECR and
**cannot be pulled and run locally** — only the server holds them and can run a game by
`policy_version_id`.

---

## Constants

| Thing | Value |
| --- | --- |
| Server | `https://softmax.com/api` (raw paths below are under `{server}/observatory`) |
| League | `league_605ff338-0a2e-4e62-aeda-559df9a9198f` (Crewrift Daily) |
| Division — Wood (top) | `div_c2be3343-f046-4c21-8674-267b5797a059` |
| Division — Dirt | `div_43e71661-556f-4fba-a6e1-bfc6e898f3d8` |
| Division — Qualifiers | `div_71f55782-07fc-43…` (all live play is here today) |
| Coworld | `cow_6b70b662-2211-4313-a50e-4a2d26585e5e` (crewrift 0.1.36 at time of writing; the league rolls versions without notice — re-check at session start) |

A game seats **8 players**: 2 imposters + 6 crew (slots `0..7`, slot index = color index). The game ends
at imposter **parity** (4 of 6 crew removed, by kills *or* vote-ejections), not at "4 kills."

---

## Auth

Two equivalent paths. Login once out of band: `uv run softmax login`.

### Raw HTTP via CoworldApiClient (preferred for the harness)

```python
from coworld.api_client import CoworldApiClient
client = CoworldApiClient.from_login(server_url="https://softmax.com/api")
http, hdr = client._http_client, client._headers()   # base_url = {server}/observatory
```

`http` is a configured `httpx` client whose `base_url` is already `{server}/observatory`, so the raw
paths below (`/v2/...`, `/jobs/...`) are used as-is. `hdr` carries the bearer/`X-Auth-Token`.

> The eval harness (`../tools/league_eval.py`) reaches directly into `client._http_client` /
> `client._headers()`. A `coworld` upgrade that renames those private attrs breaks the harness loudly —
> that is intended; do not add a `getattr` shim.

### Plain httpx with the token

```python
from softmax.auth import load_current_cogames_token
token = load_current_cogames_token()   # header: X-Auth-Token: <token>
```

This is the path `../tools/watch_v5.py` uses. The CLI token is **player-scoped** — it can submit
experience requests and read results, but player-management routes (creating a fresh player identity,
some champion flips) need the user's web session. Stage those and hand the final flip to the human.

---

## Standings (official rank)

- `GET /v2/divisions/{div}/leaderboard?include_recent_rounds=0` → entries with `mean_round_score`,
  `rounds_played`, and per-entry `recent_rounds` (recent per-round rank/score).
  CLI: `uv run coworld results <division_id>`.
- **Official rank = `mean_round_score`** — a slow cumulative per-user lifetime mean (~430 rounds ≈
  0.01/round of movement once you are strong; a rival can outrank you purely on a younger ledger).
- Per user there are **TWO players**: an *experiment* slot and a *champion* slot. "Champion" means the
  user's leaderboard-**scoring** player slot, **not** winner or #1. Judge quality by score vs the field,
  never by the champion label.

---

## Rounds (league game history)

- `client.list_rounds(league_id=…, limit=…)` / `GET /v2/rounds?league_id=…` → entries: `id`, `status`,
  `division.name`.
- `client.get_round(id)` / `GET /v2/rounds/{id}` → `results[]`: `rank`, `score`, `player.name`,
  `player.id`, `policy_version.label`. This is where "who outscored us, where" comes from.
- League-round hosted replays: `/v2/episode-requests` is **404 today** — league games are watchable only
  in the softmax.com Observatory web UI. Counterfactual experience requests (below) **do** return replay
  URLs, so confirm cruxes there, not from league rounds.

### Competition-empty workaround — rank from rounds

`top_n` champion auto-fill (see roster schema) draws **only** from `Division.type == competition` +
champion substatus. The Crewrift **Competition** division is **empty today** (all play is in
**Qualifiers**), so `top_n` returns zero opponents and the request **400s**.

**Workaround:** rank the field yourself from recent completed rounds and pass explicit seats. Aggregate
`score` per *distinct* `player.id` over a wide round window, take the top N distinct players excluding
self, and emit one `policy_ref` seat per player. `../tools/league_roster.py`
(`fetch_top_players` / `live_members`) does exactly this. When the Competition division is later
populated, `top_n` selection can replace the self-ranked roster with no caller change.

---

## Live roster (who is runnable as an opponent)

Opponents must be **live memberships** — competing, container ready. Stale pvids pulled from old round
results are rejected with 400s; player *names* are ambiguous and also 400. Use one of:

```python
league_roster.live_members(client, league_id=…)
# → ranked [{player_id, player_name, label, policy_version_id, score}]

client.list_memberships(league_id=…, division_id=…, active_only=True)
```

**Re-resolve the roster immediately before EVERY launch.** The league rolls policy versions mid-session
(crewborg v19→v21→v22, truecrew-Jr v13→v15 in a single day). Validate every pvid right before submit.

---

## Experience requests — the counterfactual engine

`POST /v2/experience-requests`, then poll `GET /v2/experience-requests/{xid}` until the request `status`
**and** every `episodes[].status` is terminal (`completed` / `failed` / `cancelled`). `404/425/429/5xx`
are transient early (read-after-write lag, scheduling) — retry within budget; see
`../tools/league_eval.py` `run_arm`.

### Body schema (post-2026-06-12 unified roster)

> **Schema version note.** The body was reworked server-side **2026-06-12** to a unified `roster`
> (one entry per seat, `policy_ref`). The **old shape** — top-level `requester` / `opponents` /
> `requester_slot` / `rotate_seats` — now **422s**. The `league-eval-design-spec.md` describes that old
> shape (Step 3's `requester{policy_version_id}` + `opponents` + `rotate_seats=false`); treat its request
> wire-format as **superseded** by this section. Its *design rationale* (single forced seat vs a strong
> field, paired arms, reuse the `results.json` verdict math) is still correct. The shipped
> `../tools/league_eval.py` is already patched to this new shape — it is current, not stale, despite the
> older `crewrift-xreq-roster-api-change` memo flagging it as predating the rework.

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

### Roster semantics (one `V2RosterParticipant` per seat)

Each roster entry's `player` is **exactly ONE of** three kinds:

- **`policy_ref`** — a label `name:vN` **or** a raw `policy_version_id` UUID. Must be an *owned* policy
  or a *live* league membership. This is how you pin a specific bot into a specific seat, including the
  counterfactual "their bot in our seat" (the rival's live pvid in seat *k*) — first-class, no
  requester/opponent distinction anymore.
- **`top_n`** — draw from the target **division's top-N champions** (Competition + champion substatus).
  **Returns zero and 400s today** because the Competition division is empty — use the rank-from-rounds
  workaround above.
- **`random`** — draw a random live member. **Draws WITH replacement** across `random` slots in one
  request, so for a true live-mix field pick *N distinct* members **client-side** and pass them as
  `policy_ref` seats; do not lean on multiple `{"random": true}` entries to get distinct opponents.

Seat pinning:

- **`slot`** (`0..7`) pins a seat. `-1` or omitted = round-robin into whatever seats are still open.
- **Forced role** is set by `game_config_overrides.slots` + `imposterCount`/`autoImposterCount=false`,
  *not* by a top-level `requester_slot`. In `../tools/league_eval.py`, the candidate's forced seat goes
  **inside** its roster entry (an inner `slot`), and `forced_slots_config` / `requester_slot_for_role`
  (from `../tools/harness_core.py`) pick a *seat of the desired role* rather than mutating the layout.
  The server rejects a top-level `requester_slot` next to a roster, so do not supply both.

Always **verify who landed where** from `episodes[].participants[].position` + `policy_version_id`
before trusting results — `random`/unpinned seats and list-order fills are not guaranteed.

### `game_config_overrides` — the experiment-control surface

Shallow-merged onto the manifest defaults and **schema-validated** (bad keys **400**, so test a new key
in a 1-episode smoke). Known-good keys:

- **`seed`** — a *real* game-config key. `sim.nim` does `initRand(config.seed)`; manifest default
  `679961`. Pinning it makes the map, tasks, and role draw **deterministic** — the crux-reproducibility
  lever. Two deterministic bots at one seed is **one observation**: spread a crux across a few seeds.
  Arbitrary pass-through keys also work via `antfarm_run.py --game-config KEY=VALUE`
  (e.g. `seed=679961`, `tasksPerPlayer=3`).
- **`maxTicks`** — `10000` is league-realistic (~7 min at 24 tps). `2000` ≈ 80 s; `300` for smokes.
  Too low makes crew win structurally 0 — calibrate the metric range before trusting an A/B.
- **`imposterCount` / `autoImposterCount: false`** + **`slots`** — pin the role layout so the candidate's
  seat is the role under test.
- **`buttonCalls: 0`** — disables emergency-meeting button presses (see Emergency button, below). The
  config key is exactly `buttonCalls`; the other three spellings **400**. Use it to ablate whether a
  strong imposter's edge is the button mechanic vs learnable behavior.
- **`killCooldown`-class** difficulty knobs to contest a saturated metric.

### `num_episodes`

≤ 100 per request. Episodes parallelize **fully** server-side (dispatch ~100 episodes / 5 s, ~2000-job
cap, ~240 warm-episode capacity, no per-user quota). N=30/arm is fine. **The server is not the
bottleneck** — the floor is realtime sim pacing (`maxticks/24` s) plus ~2 min provisioning. Run the two
A/B arms **concurrently** (the shipped harness submits both in a 2-worker pool, sharing an abort Event).

### Timeout budget formula

Scale the poll timeout from `num × maxticks`, never a flat constant:

```
arm_timeout_seconds  ≈ num × (maxticks / 24) × 3 + 900
stall_grace_seconds  ≈ (maxticks / 24) × 3 + 600
```

Zero episodes completed within `stall_grace_seconds` ⇒ a **wedged participant** (one never-connecting
bot freezes the tick-based connect timeout at tick 0 forever). **Fail loud.** A poller crash is *not* a
backend failure — re-fetch the existing `xid`, never resubmit. (`../tools/league_eval.py`
`arm_timeout_seconds` / `stall_grace_seconds`.)

---

## Per-episode artifacts

From the request detail, each `episodes[]` entry has: `id` (`ereq_…`), `job_id`, `participants[]`
(each with `position` + `policy_version_id`), and `replay_url` (public S3).

| Route | Returns |
| --- | --- |
| `GET /jobs/{job_id}/artifacts/results` | slot-indexed `results.json`: `names`, `scores`, `win`, `imposter`, `crew`, `tasks`, `kills`, `vote_players`, `vote_skip`, `vote_timeout` — length-8 arrays, slot *i* = seat *i*. The candidate's seat = the `participants` position whose `policy_version_id` matches the candidate. |
| `GET /jobs/{job_id}/artifacts/logs` | game logs |
| `GET /jobs/{job_id}/policy-logs` (+ `/{idx}`) | per-agent stdout — your bot's decision traces |

`../tools/antfarm_run.py` is the working download-everything reference: it saves replay + results + logs
per episode. The per-seat `results.json` schema is identical to what the old local harness parsed, so the
`wilson()` / `AbResult` verdict math (`../tools/harness_core.py`) is reused **verbatim**; verdict only on
**non-overlapping** Wilson CIs.

---

## Player artifacts — structured per-slot telemetry

A policy can upload **one `.zip` per seat per episode** of arbitrary structured data (sqlite, parquet,
json — the platform stores the bytes as-is). Built for exactly this optimization loop: post-hoc analysis
over large episode sets where stdout logs are too big/unstructured. Announced 2026-06-11; being
integrated into the default crewborg policy, so top-player artifacts may appear too.

### Upload contract (inside the bot)

- The runner injects a **presigned URL** as env `COWORLD_PLAYER_ARTIFACT_UPLOAD_URL`. **Absent ⇒ skip
  silently** (it is a `file://` path on local runs).
- **`PUT`** the zip with `Content-Type: application/zip`, **no auth header**, **≤ 200 MB**, **before
  container teardown** (after the final game message).
- **NEVER crash on upload failure** — a missing artifact must not fail the episode.
- Copy-paste helpers (Python `requests`; Nim `curly`/`zippy`) live in metta
  `packages/coworld/docs/coworlds-expert-agent/skills/upload-player-artifact/SKILL.md`; the full contract
  is `packages/coworld/src/coworld/docs/artifacts/PLAYER_ARTIFACT.md`.

**What to put in yours:** a *tracing profiler*, not a sampling dump — per-tick decision events (target
task + path, kill/vent opportunities seen vs taken, per-player sighting memory, vote reasoning), indexed
so 30+ episodes aggregate in one query (e.g. one sqlite table per event type). Keep it current: any new
decision mechanism must emit trace events, or the next crux analysis can't see it.

### Nim upload gotchas (notsus is Nim — measured 2026-06-11 against the live league)

- **`std/httpclient` FAILS on HTTPS** in the bot's Docker image. The build has no `-d:ssl`, so it errors
  `SSL support is not available. Cannot connect over SSL. Compile with -d:ssl`. The error is correctly
  swallowed (episode still succeeds) but the artifact **never uploads** — the server `policy-artifact`
  list is silently empty. This is the trap: the bot looks fine, the data just isn't there.
- **Use `curly`** (the Softmax-standard Nim HTTP client). `libcurl4` and `libssl.so.3` are already in the
  runtime image, so curly's HTTPS PUT just works:
  `curl.put(url, @[("Content-Type", "application/zip")], payload, 60.0'f32)`; check `response.code == 200`.
- **`curly` requires `--threads:on`** at compile time (its `{.error.}` guard) — add it to the bot
  `Dockerfile`'s `nim c` line. `--mm:orc` is the nim 2.x default, which curly also needs. notsus is
  single-threaded, so threads being on is harmless.
- Build the zip in memory with `zippy/ziparchives` `createZipArchive(entries: Table[string,string]):
  string` — **not** the top-level `zippy` import (compression only), **not**
  `ziparchives_v1.writeZipArchive` (file-path only). Both `zippy` + `curly` are already in
  `nimby.lock` / `crewrift.nimble`.
- **Episode lifecycle:** the player container is **one episode per process**. Flush at the game-over
  interstitial (`resetRoundState` site) **and** as a socket-close backstop in `runBot`'s
  `connection lost` handler — the latter is what actually fires when a game hits `maxTicks` without
  resolving.

### Download contract (in analysis)

```bash
uv run coworld episode-logs <ereq_id> --agent <slot> --artifact --download-dir logs/
```

Raw routes:

- `GET /jobs/{job_id}/policy-artifact` → lists the slots that uploaded.
- `GET /jobs/{job_id}/policy-artifact/{agent_idx}` → that slot's zip.

Serving is **Softmax-team-only today**, which for us means **ANY uploading slot is readable — including a
competitor's**, not just your own seats. The Observatory episode UI also offers the download. This is a
real lever: crewborg's per-tick sqlite trace.db exposes its beliefs/suspicion/vote decisions for mining.

---

## Replays

- **Hosted (no Docker):** `uv run coworld replay-open <ereq_id> --hosted --no-open-browser` → a viewer
  URL ending `/proxy/client/replay`. Watch/screenshot via agent-browser (sessions are per-user capped;
  expect transient 504s).
- **Local:** `uv run coworld replay <manifest> <replay.json or .json.z>` (Docker must be up).
- **Raw / authoritative oracle:** `GET <replay_url>` → the `.bitreplay` sprite-stream on public S3.
  zlib-uncompress and run the repo's `src/crewrift/replay_mine.nim` (`../tools/replay_mine.nim`) to
  reconstruct per-slot `diedTick` / distance / tasks + the full kill/vote log. A "replay hash mismatch at
  tick N" warning does **not** invalidate the reconstruction — validate by exact match of final per-slot
  roles/rewards/deaths against the recorded scores.

---

## My submissions / champion management

- List: `GET /v2/league-policy-memberships?league_id=…&mine=true&champions_only=true`
  (`uv run coworld memberships --mine --league … [--champions-only]`).
- `uv run coworld submissions --mine --league …`; `uv run coworld divisions --league …`.
- Submit: `uv run coworld submit` enters the policy in **Qualifiers**; it does **not** become champion or
  displace anything automatically.
- Promote: `POST /v2/league-policy-memberships/{lpm_id}/champion` (own memberships only).
- Retire: `POST /v2/league-policy-memberships/{id}/retire`. **Retire stale roster policies first** — the
  league rotates rounds among ALL live memberships, so an ancient low-mean policy mechanically drags the
  blended leaderboard mean.
- After ANY membership churn, **re-verify the `is_champion` flag and the leaderboard entry** — churn has
  silently cleared the flag and delisted the player. The list endpoint reads a lagging replica; a 409 on
  re-retire proves the state stuck.
- **League-visible actions (submit, retire, champion swap, external bug filing) are gated on explicit
  user approval** and done only by the lead agent, never a subagent.

---

## Policies (upload / resolve)

- Upload: `uv run coworld upload-policy <img> --name <name> [--use-bedrock]` — image **MUST** be
  `linux/amd64`. Current `coworld upload-policy` consumes the server's ECR `authorization_token`
  response. Use the manual path only as a fallback for older pinned installs that still fail before
  parsing the response. A null `pre_signed_info` means that exact image hash was already pushed —
  **not** an error. An aliased policy (same image, new name) registers without a rebuild.
- Resolve name → pvid: `client.lookup_policy_version(name=…)`.

---

## Emergency button mechanics (for button-related strategy / ablation)

*(session-derived, unverified — traced from 0.1.36 `sim.nim`, needs human review)*

- The button is a **28×34 MapRect** (`gameMap.button`) centered in a room. There is **no dedicated button
  input**: a player stands with collision-center inside the rect and sends the **A** button (bitmask
  `0x20`). On a fresh A press the sim runs `tryReport` then `tryCallButton` — A is overloaded for
  task/kill/vote/report/call-meeting depending on context.
- `tryCallButton` gates: phase must be Playing, caller alive, `buttonCallsUsed < config.buttonCalls`
  (default `ButtonCalls = 1` → **one emergency call per player per game**), collision center inside the
  rect. Success calls `startVote(VoteCalledButton)`, yanking everyone home and opening a vote.
- **The press requires being nearly stopped** — a moving press does not register reliably (notsus's
  since-removed button-reset only pressed when centered AND `|vel| <= 1`). Any bot that wants to press
  must brake first.
- Ablate via `game_config_overrides: {"buttonCalls": 0}` (see above) to isolate the button mechanic.
- Evidence: `_crewrift-0136/src/crewrift/sim.nim` — `tryCallButton` ~line 2743, A-press dispatch ~2946,
  `ButtonCalls` default ~line 70.

---

## Stats / verdict math

`harness_core.wilson(wins, n) → (p, lo, hi)` (`../tools/harness_core.py`). Verdict
(`CANDIDATE BETTER` / `BASELINE BETTER` / `INCONCLUSIVE`) only on **non-overlapping** CIs
(`../tools/league_eval.py` `run_league_ab`). INCONCLUSIVE means inconclusive — extend in 30–50-episode
chunks on the **identical** config and pool; ~13%-vs-23% effects need ~100–150/arm. Pool same-direction
deficits across related configs to clear Wilson at small n.

---

## Source files (this repo's harness)

- `../tools/league_eval.py` — runs the league A/B; the canonical post-2026-06-12 body shape.
- `../tools/league_roster.py` — `live_members` / `fetch_top_players` (rank-from-rounds workaround).
- `../tools/antfarm_run.py` — submit/poll/download reference; `--game-config KEY=VALUE`.
- `../tools/softmax_pull.py` — league/round reads that feed the roster ranker.
- `../tools/harness_core.py` — `wilson`, `AbResult`, forced-slot config.
- `../tools/replay_mine.nim` — the authoritative replay-decode oracle.
- `../tools/eval.py` — the CLI entry that drives `run_league_ab`.
