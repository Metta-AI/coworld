# Set Up a Coworld League on the Platform Ladder

How to create and maintain a seeded Coworld tournament league with the **platform ladder**
(typed `League.settings.ladder` + shared Temporal worker). This is the **only** supported path for
new Coworlds and the target for ongoing league rule changes — container (Docker) commissioners are
deprecated and closed to new use ([COMMISSIONER.md](roles/COMMISSIONER.md)).

You do **not** need a commissioner container image, a per-game `ruleset_strategy` YAML, or a
commissioner runnable in the Coworld manifest.

Public Coworld guide (ships with the [`coworld`](https://github.com/Metta-AI/coworld) package).
Canonical URL after child-repo sync:
https://github.com/Metta-AI/coworld/blob/main/src/coworld/docs/PLATFORM_LADDER_LEAGUE.md

Companion docs:

- Cut an existing container league over → [MIGRATE_TO_PLATFORM_COMMISSIONER.md](MIGRATE_TO_PLATFORM_COMMISSIONER.md)
- Deprecated container commissioners → [roles/COMMISSIONER.md](roles/COMMISSIONER.md)
- Rebuild manifests → [REBUILDING_COWORLDS.md](REBUILDING_COWORLDS.md)

Softmax teammates (private monorepo): platform REST / specs `0069`/`0071`/`0072`, skill
`temporal-platform-ladder`, retire-seeded-league.

Living production references: Crewrift Prime, Heartleaf (FFA / `swiss_neighbor`), CTF (`team_pair`).

## Default

| Path | Status | When to use |
| --- | --- | --- |
| **Platform ladder (Temporal)** | **Default** | All new leagues; changing matchmaking, seating, ranking, qualification, or divisions without shipping code |
| Container commissioner image | **Deprecated** — closed to new use | Only while maintaining a league that has not migrated, or when fairness depends on seating/scoring the ladder cannot express yet (gates removal) |

Do not build a commissioner Docker image. Use this guide instead. Holdouts →
[roles/COMMISSIONER.md](roles/COMMISSIONER.md).

## What owns the league?

| Signal | Platform ladder | Container commissioner |
| --- | --- | --- |
| Seed | `overrides.commissioner_key = "platform"` (the default when unset) | `overrides.commissioner_key = "container"`, stated explicitly |
| `leagues.commissioner_key` | `platform` (from reconcile) | `container` |
| Round brain | `settings.ladder` + Temporal workflows | Image from the Coworld manifest |
| Cadence | Continuous parent workflow; optional `settings.round_interval_minutes` paces rounds (1-minute Temporal Schedule is only a liveness backstop) | `commissioner_config.schedule_interval_minutes` (overridable via `settings.round_interval_minutes`) |
| Standings | Platform Elo or `score` standing + published leaderboards | Opaque `commissioner_state` from the container |
| Commissioner image / runnable | **Not required** | Required in the Coworld manifest |

`commissioner_key=platform` alone is not enough. Temporal only runs when `settings.ladder.enabled`
is true. Writing a ladder document while the seed still owns `container` does not start Temporal
rounds.

## Behavior you get

Platform ladder is player-centric:

- Each player contributes **exactly one champion** `PolicyVersion` per division round.
- Benched / non-champion competing versions do **not** seat.
- Ranking is `elo` (default) or `score` (EWMA / mean / max standing over round scores).
- Optional ladder-wide **qualification** is a self-play experience plus a boolean gate over episode
  evidence — not a separate Qualifiers division with its own container stage.
- Optional `leader_slot_config` overlays the displayed first-place champion's seats (e.g. CTF crown
  skin) when the planner freezes a round.
- Episode execution still uses the existing Coworld job runner (Kubernetes). Temporal only
  coordinates planning, dispatch, settlement, and ranking / membership updates.
- `settings.counterfactual_eval` is a **sibling** of `ladder` (measurement / auto-on-upload). Preserve
  it on settings POST; it is not ladder admission.

Persistent Coworlds use the same ladder owner with `ladder.persistent` instead of episodic seating.
Each cycle freezes the active player/policy memberships, reconciles one durable runtime per player,
then ingests the oldest sealed `coworld.recorded_window.v1` interval containing exactly that roster.
Those windows become completed `RoundEpisode` evidence directly: the workflow creates no
`EpisodeRequest` and dispatches no bounded job. The runtime game overlay is selected by
`persistent.runtime.game_config_overlay_secret`; the seed's existing private commissioner overlay
must provide `persistent_window_feed_config`, and its
`persistent_window_floor_wall_clock_ms` remains the cutover fence. Disabling the ladder or returning
the seed to container ownership stops only runtimes last authored by the platform reconciler.

## Choose a seating strategy

Pick from the game shape, not from the old container YAML name. Strategy knobs are listed below.

| Game shape | Strategy | Notes |
| --- | --- | --- |
| FFA / N distinct champions share an episode (Heartleaf, Crewrift) | `swiss_neighbor`, `round_robin`, `balanced_rotation`, or `random_fill` | When champions < seats, set `insufficient_players` (usually `multiple_seats`) |
| Two-team clone matchups (CTF: 2 champions × half the seats) | `team_pair` | Even seat count; each unordered pair plays both side assignments; clone seats are filler-marked |
| N-team clone matchups (Four Score: 4×8) | `team_n` | `team_count` required and must divide seats; do **not** use `team_pair` |
| Variable table size (Nightshift) | `variable_seat` | Requires `seat_count_min`, `seat_count_max`, `min_episodes_per_entrant`; manifest must allow the range |
| Scaling headcount (Muster) | `scaling_roster` | Requires ascending `seat_rungs`; prefer `ranking.algorithm: score` with `standing_aggregation: max` |
| Full self-play / every-seat clone (Tribal Village competition) | `clone_fill` | Requires `episodes_per_entrant`; optional `clone_score_aggregation` |
| Custom bracket / elimination / opaque scoring | Not supported | Keep an existing container commissioner until the platform grows a strategy that fits — do not build a new one for a new league |

Insufficient-player modes (ladder-wide):

| Mode | Behavior |
| --- | --- |
| `multiple_seats` | Duplicate real policies into filler-marked seats (no credit on duplicates). Easiest for small rosters. |
| `filler_policy` | Fill from league filler versions (must already be configured on the league). |
| `do_not_run` | Skip the round until enough real champions exist (`team_pair` needs 2; `team_n` needs `team_count`). |

Volume / strategy knobs (optional unless noted; omit to keep derived defaults; rejected on strategies that do not consume them):

| Field | Strategies | Effect |
| --- | --- | --- |
| `min_episodes_per_entrant` | `round_robin`, `swiss_neighbor`; **required** on `variable_seat` | Repeat seating until every entrant plays at least this often |
| `num_episodes` | `balanced_rotation`, `random_fill`; optional cap / sample count on `team_n` | Exact episode count (or `team_n` matchup cap; required with `elo_softmax`) |
| `neighbor_window` | `swiss_neighbor` | Nearest neighbors each entrant meets (default 1) |
| `seat_count_min` / `seat_count_max` / `seat_count_weights` | `variable_seat` | Per-episode seat sample range (weights optional, uniform default) |
| `seat_rungs` / `episodes_per_round` | `scaling_roster` | Ascending legal headcounts; copies per round (default 1) |
| `seat_count` / `episodes_per_entrant` / `clone_score_aggregation` | `clone_fill` | Seat override; episodes per champion; mean/sum fold of clone seats |
| `team_count` / `matchmaking` / `matchmaking_temperature` / `allied_teams` | `team_n` | Team count; `random` or `elo_softmax` sampling; ally partition |

Cadence: by default the parent starts the next eligible round as soon as the previous cycle settles
(free-run). To pace a league whose episodes finish quickly, set the top-level
`settings.round_interval_minutes` (a sibling of `ladder`, not inside it; max four weeks): a
division's next round is then due only once that many minutes have passed since its latest round
was created. The interval is enforced in the due-check from the division's own round history, so it
survives worker restarts and concurrent parents. A manual `POST /v2/leagues/{id}/trigger-round`
starts the next cycle promptly, bypassing the interval once. The parent re-snapshots settings at
least every 15 minutes while pacing, so interval changes and pause take effect within that window.

## Choose a ranking algorithm

| Board you want | Config | Notes |
| --- | --- | --- |
| Pairwise skill (win/loss / relative score) | `algorithm: elo` | Default. `k_factor`, `initial_rating`, `round_scoring_rule: mean \| ewma` |
| Continuous score / ATH / glory | `algorithm: score` | `standing_aggregation: ewma \| mean \| max`; `half_life_hours` required for EWMA |

Movement rules gate on Elo rating thresholds or, for `score`, standing thresholds (`minimum_standing` /
`maximum_standing`). Use the JSON examples in this guide as the working schema.

## Preconditions

1. The Coworld is uploaded and **canonical** (seed create looks up the canonical coworld by name).
2. You know the coworld name, seat count (`num_agents` on the league variant), and intended game shape.
3. Shared Temporal ladder worker is live in the target environment (prod already runs it for Crewrift /
   Heartleaf / CTF).
4. You can create the seed: Softmax team members, or the **canonical Coworld owner** for that
   `coworld_name` (via `coworld league create` / `POST /v2/coworld-league-seeds`). Team tokens still
   need `X-Use-Elevated-Privileges: true` for team-only follow-up routes.

Certification is independent of league ownership. Prefer a certified Coworld before opening a public
league (`coworld certify` / `coworld upload-coworld`).

## Create a new platform league

Greenfield sequence. Keep the league paused (or ladder disabled) until topology and the ladder
document look right.

### 1. Create the seed with platform ownership

```bash
POST /v2/coworld-league-seeds
{
  "coworld_name": "<coworld_name>",
  "league_key": "<league_key>",
  "league_name": "<league_name>",
  "template": "commissioner_driven",
  "enabled": true,
  "overrides": {
    "commissioner_key": "platform"
  }
}
```

Notes:

- Prefer `template: "commissioner_driven"` for new seeds. Template only matters for legacy container
  wiring; platform leagues ignore container stage recipes.
- **Do not** set `leagues.commissioner_key` in SQL. Reconcile overwrites it from the seed every
  ~5s.
- `commissioner_key` is optional over the API — unset means `platform`, and create writes the
  resolved key into the row. A row inserted by hand in SQL is not stamped, and a stored row that
  does not name its commissioner fails to parse, so always include the key there.
- Seed create runs reconcile immediately. Expect `leagues.commissioner_key = platform` and
  `commissioner_config = null`.
- Platform seeds do **not** auto-create Qualifiers / Competition divisions. You declare topology
  next. Until you do — and until `ladder.enabled` is true — the league schedules **nothing**;
  reconcile logs a warning saying exactly that when it creates the league.
- You do **not** need a commissioner runnable in the Coworld manifest for platform ownership. Omit
  `commissioner_runnable_id` unless you intentionally keep a container path around for something else.

Verify:

```sql
SELECT l.league_id, l.commissioner_key, l.commissioner_config, s.overrides
FROM leagues l
JOIN games g ON g.id = l.game_id
JOIN coworld_league_seeds s ON s.coworld_name = g.coworld_name
WHERE g.coworld_name = '<coworld_name>';
```

### 2. Declare active divisions

```bash
PUT /v2/leagues/{league_id}/divisions
{
  "divisions": [
    {"name": "Competition", "level": 1, "type": "competition", "hidden": false}
  ]
}
```

Most Coworlds want a single Competition division. Omit Qualifiers unless you still need a
human-visible staging division; platform admission gates belong in `settings.ladder.qualification`,
not in a legacy Qualifiers stage.

Omitted existing divisions are archived only when they have neither live memberships nor active
rounds. Replaying the same declaration is a no-op.

After ladder `enabled: true`, league-scoped `cmr_` tokens cannot rewrite topology — use a team
credential.

### 3. Write the ladder document (still disabled)

UI: open the league in Observatory → **League settings** → configure strategy, insufficient-player
mode, ranking, divisions, optional qualification / leader overlay → save with ladder **disabled**
first if you want a review step.

API (POST replaces the whole settings document — read first and preserve siblings such as
`counterfactual_eval`):

```bash
GET  /v2/leagues/{league_id}/settings
POST /v2/leagues/{league_id}/settings
```

Minimal Competition-only body (merge into the existing `settings` object; replace division ids/names
with live values from `GET /v2/divisions` or the topology response):

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

Shape-specific scheduler swaps:

```json
"scheduler": {
  "strategy": "team_pair",
  "insufficient_players": "do_not_run"
}
```

```json
"scheduler": {
  "strategy": "team_n",
  "insufficient_players": "do_not_run",
  "team_count": 4,
  "num_episodes": 48
}
```

```json
"scheduler": {
  "strategy": "variable_seat",
  "insufficient_players": "multiple_seats",
  "seat_count_min": 4,
  "seat_count_max": 8,
  "min_episodes_per_entrant": 1
}
```

Continuous-score ranking example (swap the `ranking` block):

```json
"ranking": {
  "algorithm": "score",
  "round_scoring_rule": "mean",
  "standing_aggregation": "ewma",
  "half_life_hours": 24,
  "initial_standing": 0.0
}
```

Optional leader decoration (CTF crown):

```json
"leader_slot_config": { "skin": "crown" }
```

Deploy backend before the ladder worker before writing a non-null `leader_slot_config` (Temporal
patch `leader-slot-config`).

After POST, compare `settings.ladder` to `effective_ladder_config` on the GET response.

### 4. Enable, unpause, prove one cycle

1. `POST` settings again with `ladder.enabled: true` (or toggle enable in the UI). Enabling clears
   published division leaderboards so Standings cannot serve a stale board under a new ranking label.
2. Ensure rounds are not paused: `POST /v2/leagues/{league_id}/rounds-paused` with
   `{"paused": false}`.
3. Trigger once: `POST /v2/leagues/{league_id}/trigger-round`.
4. Confirm:
   - Temporal workflow id `ladder-{league_id}` on task queue `league-ladder`
   - A Competition `Round` with `commissioner_key=platform` and a frozen `episode_plan`
   - EpisodeRequests run through the job runner
   - Round completes → leaderboard publishes (`score_label: "Elo"` or the score standing view)
   - Parent starts another cycle (or exits for pause / `do_not_run` / retries exhausted)

### 5. Admit players

Players submit policies as usual (`coworld submit` / Observatory submit). Optional
`settings.ladder.qualification` gates placement with platform-owned self-play. Without qualification,
placed submissions enter competition directly.

Optional `settings.ladder.players_per_user` caps how many distinct active players one user may hold
(`1` = single seat per user). Unset defers to the Coworld manifest's `players_per_user` (default 2).
Checked when a membership is placed or promoted into competing — never a retroactive sweep, so
lowering it on a live league converges as affected users next submit or promote; the surplus
players' live memberships are deactivated, newest memberships surviving. Applies even while the
ladder is disabled.

## Maintain an existing platform league

| Change | How |
| --- | --- |
| Matchmaking / volume / ranking / qualification / leader overlay | Edit ladder in Observatory **League settings**, or GET → merge → POST `/settings` |
| Per-user seat cap (`players_per_user`, 1 = single seat) | GET → merge → POST `/settings` (no UI control; applies on next placement/promotion, no retroactive sweep) |
| Active divisions / archive side divisions | `PUT /v2/leagues/{league_id}/divisions` (team credential once ladder enabled) |
| Pause scheduling | `POST .../rounds-paused` `{"paused": true}` — in-flight rounds still finish |
| Kick a cycle | `POST .../trigger-round` |
| Game-of-week | Find the seed ID with `GET /v2/coworld-league-seeds`, then `PUT /v2/coworld-league-seeds/{seed_id}/game-of-week` |
| Counterfactual measurement knobs | Edit sibling `settings.counterfactual_eval` (preserve on every settings POST) |
| Retire the league | Disable the seed (`PATCH` / disable on `/v2/coworld-league-seeds/{seed_id}`) |

Hard rules when editing:

1. **Settings POST replaces the whole document.** Preserve non-ladder sibling fields you still need
   (`counterfactual_eval`, etc.).
2. **Seed override PATCH replaces the whole `overrides` object**, except `commissioner_key`.
   Re-include every override you want to keep (`is_game_of_week`, overlay secrets, etc.). An omitted
   `commissioner_key` keeps the stored one, so no unrelated seed edit can move a league between
   commissioners; change ownership by sending the key.
3. **Never dual-write.** Do not flip a live container league to platform (or back) without pause +
   drain. Use [MIGRATE_TO_PLATFORM_COMMISSIONER.md](MIGRATE_TO_PLATFORM_COMMISSIONER.md) for cutovers.
4. **Do not invent scheduler strategies in a game repo.** If the platform cannot seat your game
   fairly, that is a platform feature request — not a reason to silently stand up a second writer.

## Common mistakes

| Mistake | What happens |
| --- | --- |
| Seed created with `commissioner_key: container` | Reconcile expects a commissioner runnable; no Temporal ladder |
| New platform league left at step 1 (no divisions, no ladder) | League exists and schedules nothing — finish steps 2 and 3 |
| Ladder written while seed is still `container` | Document stores, but the container scheduler still owns rounds |
| `commissioner_key=platform` but `ladder.enabled=false` | No Temporal parent; league sits idle |
| Expecting all competing policy versions to seat | Only champions seat (one per player) |
| Keeping empty Qualifiers "just in case" | Prefer Competition-only + optional `ladder.qualification` |
| Using FFA strategies for CTF-style team clones | Unfair seating; use `team_pair` |
| Using `team_pair` for Four Score / N>2 teams | Wrong topology; use `team_n` with the real `team_count` |
| Forcing Elo on a continuous-score / ATH board | Prefer `ranking.algorithm: score` |
| Dropping `counterfactual_eval` on settings POST | Sibling knobs reset / disappear; always merge |
## Auth cheatsheet

```bash
# Softmax team token (seeds, settings, topology, pause, trigger)
TOKEN=$(uv run python -c "from softmax.auth import load_user_token; print(load_user_token(server='https://softmax.com/api'))")
BASE=https://softmax.com/api/observatory/v2

curl -sS -H "Authorization: Bearer $TOKEN" -H "X-Use-Elevated-Privileges: true" \
  -H "Content-Type: application/json" \
  -d '{"coworld_name":"my_game","league_key":"default","league_name":"My Game","template":"commissioner_driven","overrides":{"commissioner_key":"platform"}}' \
  "$BASE/coworld-league-seeds"
```

Local UI: `http://localhost:3002` (or your port-offset frontend) → league → League settings → Run
round now. Local Temporal smoke steps: skill `temporal-platform-ladder`.

## See also

- Migrate an existing container league → [MIGRATE_TO_PLATFORM_COMMISSIONER.md](MIGRATE_TO_PLATFORM_COMMISSIONER.md)
- Deprecated container commissioners → [roles/COMMISSIONER.md](roles/COMMISSIONER.md)
- Rebuild Coworld manifests → [REBUILDING_COWORLDS.md](REBUILDING_COWORLDS.md)
- Public GitHub: https://github.com/Metta-AI/coworld/blob/main/src/coworld/docs/PLATFORM_LADDER_LEAGUE.md
