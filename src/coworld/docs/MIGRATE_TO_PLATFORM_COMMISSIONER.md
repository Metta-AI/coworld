# Migrate a League to the Platform Commissioner

Public Coworld guide (ships with the [`coworld`](https://github.com/Metta-AI/coworld) package).
Canonical URL after child-repo sync:
https://github.com/Metta-AI/coworld/blob/main/src/coworld/docs/MIGRATE_TO_PLATFORM_COMMISSIONER.md

> **Container (Docker) commissioners are deprecated.** This page is no longer just an upgrade
> path — it is the **required** path for every container league whose shape the ladder can express,
> which is all but one of the shapes in [When not to cut over yet](#when-not-to-cut-over-yet) below.
> The single exception is that table's last row (custom brackets / opaque scoring the ladder cannot
> express). Those leagues gate the deprecation's delete phase, and unblocking them means building
> the missing ladder capability — a decision this deprecation makes, not something the table below
> says on its own. Migration is phase 2; once no enabled league is left on `container`, the
> container commissioner code is deleted. Softmax teammates: see the phase table in
> `docs/ai/onboarding/services/coworlds/commissioner-config.md` (private monorepo).

How to cut a seeded Coworld league over from the **container commissioner** (per-league WebSocket
image + round runner) to the **platform commissioner** (typed `League.settings.ladder` + shared
Temporal worker).

Companion docs:

- **New leagues (preferred):** skip this page → [PLATFORM_LADDER_LEAGUE.md](PLATFORM_LADDER_LEAGUE.md)
- Deprecated container commissioners → [roles/COMMISSIONER.md](roles/COMMISSIONER.md)
- Public package home → [README.md](README.md)

Softmax teammates (private monorepo): platform REST / token lifecycle
(`docs/ai/onboarding/services/coworlds/platform-commissioner-api.md`), ladder specs `0069` / `0072`,
skill `temporal-platform-ladder`, retire-seeded-league.

Crewrift Prime, Heartleaf, and CTF are living production cutovers. For greenfield setup after
migration lessons, prefer [PLATFORM_LADDER_LEAGUE.md](PLATFORM_LADDER_LEAGUE.md).

## Which system owns the league?

| Signal | Container commissioner | Platform commissioner |
| --- | --- | --- |
| `leagues.commissioner_key` | `container` | `platform` |
| Seed ownership | `overrides.commissioner_key = "container"` (explicit on every row since migration `seedkey0075`) | `overrides.commissioner_key = "platform"` |
| Round brain | Commissioner container image from the Coworld manifest | Typed `settings.ladder` + Temporal workflows |
| Cadence | `commissioner_config.schedule_interval_minutes` | Continuous parent workflow; 1-minute Temporal Schedule is only a liveness backstop |
| Standings | Opaque `commissioner_state` written by the container | Platform Elo or `score` standing + published leaderboards |

`commissioner_key=platform` alone is not enough. The Temporal ladder only runs when
`settings.ladder.enabled` is true. Conversely, writing a ladder document while the league is still
`container` does not stop the container scheduler.

## Hard rules

1. **Never dual-write.** Do not leave the container scheduler scheduling rounds while Temporal owns
   the same divisions.
2. **Ownership is a seed property.** Do not set `leagues.commissioner_key` in SQL. Reconcile overwrites
   it from `coworld_league_seeds.overrides` every cycle (~5s).
3. **Pause and drain before flipping.** An in-flight container round must finish (or be aborted to a
   terminal state) before the seed override changes.
4. **Settings POST replaces the whole document.** Read current settings first and preserve any
   non-ladder sibling fields you still need. Enabling `ladder.enabled` clears every division's
   published `leaderboard_config` so Standings cannot serve stale container 0–1 scores under an
   Elo column before the first platform round publishes ratings.
5. **Seed override PATCH replaces the whole `overrides` object** — with one exception. Re-include
   every override you want to keep (`is_game_of_week`, overlay secrets, etc.) when you add
   `commissioner_key`. `commissioner_key` itself is the exception: omit it and the PATCH carries the
   stored value forward instead of falling to the seed default (`"platform"`), so no unrelated seed
   edit can hand a league to the other commissioner. Changing ownership means sending the key.

## When not to cut over yet

Do **not** migrate a league whose fairness depends on seating or scoring the platform ladder cannot express.
Pick the matching strategy from the game shape (details in
[PLATFORM_LADDER_LEAGUE.md](PLATFORM_LADDER_LEAGUE.md)):

| Game shape | Platform strategies | Action |
| --- | --- | --- |
| FFA / N distinct champions per episode (Heartleaf, Crewrift) | `round_robin` / `balanced_rotation` / `swiss_neighbor` / `random_fill` + Elo | Follow this guide |
| Two-team clone matchups (CTF, Cogtank) | `team_pair` + Elo | Follow this guide; usually `insufficient_players: do_not_run` |
| Four-team / N-team clone (Four Score: 4×8) | `team_n` + Elo (`team_count` must divide seats) | Follow this guide — do **not** use `team_pair` |
| Variable table size (Nightshift) | `variable_seat` + usually `score` | Follow this guide; manifest must allow the seat range |
| Scaling headcount / glory (Muster) | `scaling_roster` + `score` / `max` | Follow this guide |
| Full self-play competition (Tribal Village) | `clone_fill` + usually `score` | Follow this guide |
| Custom brackets / opaque scoring the ladder cannot express | — | Keep the container commissioner |

Do **not** cut a CTF-shaped league over with FFA strategies, or Four Score with `team_pair` — those recreate
free wins or wrong team topology. Continuous-score boards that should stay score-sorted use
`ranking.algorithm: score` (fresh standings on cutover; container EWMA / OpenSkill numbers do not carry over).

## Behavior changes to expect

Platform ladder v1 is deliberately player-centric:

- Each player contributes **exactly one champion** `PolicyVersion` per division round.
- Benched / non-champion competing versions do **not** seat. A league that previously seated every
  competing version (e.g. 40 policies across 7 players) will drop to the champion count (7).
- If champions < Coworld seat count, pick one insufficient-player mode for the whole ladder:
  - `multiple_seats` — duplicate real policies into filler-marked seats (no credit on duplicates);
    easiest when roster is small.
  - `filler_policy` — fill from league filler versions (must be configured on the league).
  - `do_not_run` — skip the round until enough real champions exist.
- Ranking is `elo` (default) or `score` (EWMA / mean / max standing). Container OpenSkill / EWMA
  standings do **not** carry over automatically. Prefer fresh standings unless a separately reviewed
  one-off migration exists.
- Legacy Qualifiers divisions are not ladder topology. Platform qualification is an optional
  ladder-wide self-play gate in `settings.ladder.qualification`. Archive unused Qualifiers /
  side divisions the way Crewrift archived Crew / Imposters / Qualifiers.

## Preconditions

Confirm all of these before touching prod:

1. Shared Temporal ladder worker is live in the target environment (Crewrift Prime already proves
   prod). Worker authenticates with a machine token scoped to `commissioner:platform` only.
2. Backend schedule / qualification reconcilers can talk to Temporal Cloud.
3. You know the league id, coworld name, Competition `division_id`, seat count, and active champion
   count.
4. You have Observatory credentials that can call `/v2/coworld-league-seeds` and league settings /
   pause routes (canonical Coworld / game owner, or Softmax team).

Inventory the league via the v2 API (`GET /v2/leagues/{id}`, divisions, memberships, recent rounds).
Softmax teammates may also use read-only prod SQL. Example inventory queries:

```sql
SELECT l.league_id, l.name, l.commissioner_key,
       l.rounds_paused_at IS NOT NULL AS paused,
       l.settings->'ladder'->>'enabled' AS ladder_enabled,
       g.coworld_name, s.overrides
FROM leagues l
JOIN games g ON g.id = l.game_id
LEFT JOIN coworld_league_seeds s ON s.coworld_name = g.coworld_name
WHERE l.league_id = '<league_id>';

SELECT d.division_id, d.name, d.level, d.type, d.archived_at IS NOT NULL AS archived
FROM divisions d
JOIN leagues l ON l.id = d.league_id
WHERE l.league_id = '<league_id>'
ORDER BY d.level;

SELECT count(DISTINCT player_id) AS players,
       count(*) FILTER (WHERE is_champion) AS champions,
       count(*) FILTER (WHERE status = 'competing' AND end_time IS NULL) AS competing_active
FROM league_policy_memberships m
JOIN leagues l ON l.id = m.league_id
WHERE l.league_id = '<league_id>' AND m.end_time IS NULL;

SELECT r.round_id, r.status::text, r.commissioner_key, r.created_at
FROM rounds r
JOIN divisions d ON d.id = r.division_id
JOIN leagues l ON l.id = d.league_id
WHERE l.league_id = '<league_id>'
ORDER BY r.created_at DESC
LIMIT 10;
```

## Cutover procedure

### 1. Draft the ladder document

Start from the JSON examples below (and shape-specific swaps in
[PLATFORM_LADDER_LEAGUE.md](PLATFORM_LADDER_LEAGUE.md)).
Replace every division id/name with live values. Keep `enabled: false` until after ownership flips.

Minimal Competition-only shape (Crewrift-like):

```json
{
  "ladder": {
    "enabled": false,
    "scheduler": {
      "strategy": "swiss_neighbor",
      "insufficient_players": "multiple_seats",
      "min_episodes_per_entrant": 8
    },
    "fulfillment": {
      "allowed_failures": 0.05,
      "retry_times": 2
    },
    "ranking": {
      "algorithm": "elo",
      "initial_rating": 1500.0,
      "k_factor": 32.0,
      "round_scoring_rule": "mean"
    },
    "divisions": [
      {
        "division_id": "div_…",
        "name": "Competition",
        "disqualify_after_consecutive_failures": 3
      }
    ]
  }
}
```

Knobs that matter:

| Field | Notes |
| --- | --- |
| `scheduler.strategy` | FFA: `round_robin` / `balanced_rotation` / `swiss_neighbor` / `random_fill`; teams: `team_pair` / `team_n`; also `variable_seat`, `scaling_roster`, `clone_fill` — see [PLATFORM_LADDER_LEAGUE.md](PLATFORM_LADDER_LEAGUE.md) |
| `scheduler.insufficient_players` | Required decision when champions < seats (or < `team_count` for team strategies) |
| Strategy-specific knobs | `min_episodes_per_entrant`, `num_episodes`, `neighbor_window`, `team_count`, seat-range / rung / clone fields — validated per strategy |
| `ranking.algorithm` | `elo` (default) or `score` for continuous / ATH boards |
| `leader_slot_config` | Optional first-place seat overlay (e.g. CTF crown); null leaves plans unchanged |
| `fulfillment.allowed_failures` | Fraction `0.0`–`1.0`, not a slot count |
| `qualification` | Optional; omit to admit placed submissions straight into competition |
| Division blocks | Identity + optional promotion/relegation/DQ only — no per-division scheduler |

Map container knobs carefully: container `episodes` / seating YAML do not translate 1:1. Re-derive from
roster size, seat count, and desired appearances per champion. Shape-specific JSON examples:
[PLATFORM_LADDER_LEAGUE.md](PLATFORM_LADDER_LEAGUE.md).

### 2. Pause and drain the container commissioner

```bash
# Pause new scheduling
POST /v2/leagues/{league_id}/rounds-paused
{"paused": true}
```

Wait until every non-terminal container round reaches a terminal status (`completed`, failed/aborted
equivalents). Pause alone does not kill an in-flight round; its supervisor keeps the lease until
finish or lease failure.

Do **not** flip the seed while a `running` / `claimed` container round still exists.

### 3. Flip ownership on the seed

Read the current seed, then PATCH with the full overrides object you want after cutover:

```bash
GET  /v2/coworld-league-seeds
# find the intended coworld_name / league_key row and copy its lseed_... ID

PATCH /v2/coworld-league-seeds/{seed_id}
{
  "overrides": {
    "commissioner_key": "platform"
    // plus any previously present overrides you still need
  }
}
```

The route commits and runs `reconcile_seed_coworld_leagues` for that coworld. Within one cycle:

- `leagues.commissioner_key` becomes `platform`
- container `commissioner_config` is cleared (`null`) for platform leagues
- the container round runner stops claiming new work for this league

Verify:

```sql
SELECT l.commissioner_key, l.commissioner_config, s.overrides
FROM leagues l
JOIN games g ON g.id = l.game_id
JOIN coworld_league_seeds s ON s.coworld_name = g.coworld_name
WHERE l.league_id = '<league_id>';
```

Expect `commissioner_key = 'platform'` and seed overrides containing `"commissioner_key": "platform"`.

### 4. Write ladder settings while still paused

```bash
GET  /v2/leagues/{league_id}/settings
POST /v2/leagues/{league_id}/settings
# body = previous settings object with ladder block merged in, enabled: false
GET  /v2/leagues/{league_id}/settings
# compare settings.ladder to effective_ladder_config
```

Optional cleanup (Crewrift pattern): archive Qualifiers and any side competition divisions that are
not in the ladder document so the UI and reconciler are not confused by dead topology.

### 5. Enable, unpause, and prove one cycle

1. `POST` settings again with `ladder.enabled: true` (league still paused).
2. Unpause: `POST .../rounds-paused` with `{"paused": false}`.
3. Trigger once: `POST /v2/leagues/{league_id}/trigger-round` (platform path starts
   `LeagueLadderWorkflow` under the deterministic id `ladder-{league_id}`).
4. Confirm in Temporal (task queue `league-ladder`):
   - parent `ladder-{league_id}` is running
   - a `RoundWorkflow` child starts for Competition
5. Confirm on the platform:
   - round persists a frozen plan before dispatch
   - EpisodeRequests run through the existing runner
   - round waits until every planned slot is terminal
   - Elo / leaderboard update once
   - parent begins another cycle or exits for a documented reason (pause, `do_not_run`, retries exhausted)

### 6. Soak, then remove container-only leftovers

After at least one clean Temporal cycle (preferably several):

- Leave any per-league commissioner Deployment / credential unused (scale to zero / delete only after
  soak — Crewrift still had a dedicated Deployment path during early migration).
- Do not delete the Coworld's commissioner runnable from the manifest solely because the league moved;
  other environments or tools may still reference it. Ownership for this league is the seed override,
  not the absence of a container image.

## Rollback

If the platform ladder misbehaves before you are confident:

1. Pause the league (`rounds-paused: true`).
2. Let in-flight `RoundWorkflow` children settle (cancel wedged EpisodeRequests if a child is pinned).
3. Set `ladder.enabled: false` via settings POST.
4. PATCH the seed overrides with `"commissioner_key": "container"`, re-including every other override
   you need. Reconcile restores container ownership and regenerates `commissioner_config` from the
   seed template. Omitting the key does **not** roll back — it keeps `platform`, because an omitted
   key carries the stored value forward.
5. Unpause only after container rounds are the intended owner again.

Fresh Elo ratings written during the brief platform window will not reconstruct prior container
standings. Treat rollback as a competitive discontinuity unless you have a reviewed state migration.

## Worked example sketch: Heartleaf

Production inventory at the time of the first cutover draft:

| Field | Value |
| --- | --- |
| League | `league_f831ba75-e81b-4796-b8c6-cd10be18c0bf` (Heartleaf) |
| Coworld / seed | `heartleaf` |
| Before | `commissioner_key=container`, seed overrides `{}`, `settings` null |
| Divisions | Qualifiers (empty) + Competition `div_396961a3-58af-4276-abc7-3f45fb7fe337` |
| Roster | 7 players / 7 champions / many benched competing versions |
| Seats | league variant `num_agents: 9` → needs `multiple_seats` or fillers |
| Standings | `commissioner_state` null → fresh Elo |

Sequence: pause → drain running container round →
find Heartleaf's seed ID with `GET /v2/coworld-league-seeds`, then PATCH
`/v2/coworld-league-seeds/{seed_id}` with `{"overrides":{"commissioner_key":"platform"}}` →
write Competition-only ladder (`enabled: false`) → archive Qualifiers → enable → unpause →
`trigger-round` → verify Temporal + leaderboard.

## See also

- Greenfield / day-2 platform leagues → [PLATFORM_LADDER_LEAGUE.md](PLATFORM_LADDER_LEAGUE.md)
- Deprecated container path → [roles/COMMISSIONER.md](roles/COMMISSIONER.md)
- Public GitHub: https://github.com/Metta-AI/coworld/blob/main/src/coworld/docs/MIGRATE_TO_PLATFORM_COMMISSIONER.md
