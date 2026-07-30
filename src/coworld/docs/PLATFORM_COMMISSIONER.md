# Platform Commissioner (League Ladder)

How a Coworld author or Softmax operator runs a seeded tournament league on the
**platform commissioner**: typed `League.settings.ladder` plus a shared Temporal
worker — not a per-league commissioner container image.

This is the recommended ownership model for new leagues and for cutovers from
legacy container commissioners. Softmax teammates have the full operator runbook
in the private Metta repo:

- `docs/ai/onboarding/services/coworlds/migrate-to-platform-commissioner.md`
- `docs/ai/onboarding/services/coworlds/platform-commissioner-api.md`
- `docs/ai/onboarding/services/coworlds/commissioner-config.md` (container-only
  rule changes)
- `docs/specs/0072-ladder-matching-ranking-extensions.md` (matching / ranking
  options)

The [Commissioner role](roles/COMMISSIONER.md) still describes the **container**
WebSocket runnable contract used when `commissioner_key=container`.

## Platform vs container ownership

| Signal | Container commissioner | Platform commissioner |
| --- | --- | --- |
| `leagues.commissioner_key` | `container` | `platform` |
| Seed ownership | `coworld_league_seeds.overrides` omits `commissioner_key` (default) | `overrides.commissioner_key = "platform"` |
| Round brain | Commissioner container image from the Coworld manifest | Typed `settings.ladder` + Temporal workflows |
| Cadence | `commissioner_config.schedule_interval_minutes` | Continuous parent workflow; a 1-minute Temporal Schedule is only a liveness backstop |
| Standings | Opaque `commissioner_state` written by the container | Platform Elo / score state + published leaderboards |

`commissioner_key=platform` alone is not enough. The Temporal ladder only runs
when `settings.ladder.enabled` is true. Writing a ladder document while the
league is still `container` does not stop the container scheduler.

You do **not** need a commissioner runnable in the Coworld manifest for a
platform-owned league. Keep a container commissioner in the package only if you
still support container environments or local experiments that use it.

## Prerequisites

Confirm before flipping ownership:

1. The shared Temporal ladder worker is live in the target environment (prod is
   already proven by leagues such as Crewrift Prime).
2. You have a Softmax team credential that can call
   `/v2/coworld-league-seeds`, league settings, and pause routes.
3. You know the league id, coworld / seed name, Competition `division_id`, seat
   count, and active champion count.
4. The league’s fairness shape matches a platform seating strategy (see below).
   Prefer a **Competition-only** ladder: archive unused Qualifiers / side
   divisions rather than modeling legacy qualifier topology in `settings.ladder`.

## Hard rules

1. **Never dual-write.** Do not leave the container scheduler scheduling rounds
   while Temporal owns the same divisions.
2. **Ownership is a seed property.** Do not set `leagues.commissioner_key` in
   SQL. Seed reconcile overwrites it from `coworld_league_seeds.overrides` every
   cycle (~5s).
3. **Pause and drain before flipping.** An in-flight container round must finish
   (or be aborted to a terminal state) before the seed override changes.
4. **Settings POST replaces the whole document.** Read current settings first
   and preserve any non-ladder sibling fields you still need. Enabling
   `ladder.enabled` clears every division’s published `leaderboard_config` so
   Standings cannot serve stale container scores under a platform column before
   the first platform round publishes ratings.
5. **Seed override PATCH replaces the whole `overrides` object.** Re-include
   every override you want to keep (`is_game_of_week`, overlay secrets, etc.)
   when you add `commissioner_key`.

## Cutover (high level)

Operate against Observatory API base `…/v2` with a Softmax team token.

1. **Draft** a Competition-only `settings.ladder` document with
   `enabled: false`. Pick seating + ranking (next sections).
2. **Pause** the league: `POST /leagues/{league_id}/rounds-paused` with
   `{"paused": true}`.
3. **Drain** until every non-terminal container round is terminal. Do not flip
   ownership while a `running` / `claimed` container round exists.
4. **Seed override** — `GET /coworld-league-seeds`, then
   `PATCH /coworld-league-seeds/{coworld_name}` with the full `overrides` object
   including `"commissioner_key": "platform"` (plus any overrides you still
   need). Reconcile sets `leagues.commissioner_key=platform` and clears
   container `commissioner_config`.
5. **Write ladder settings** while still paused:
   `GET /leagues/{league_id}/settings`, merge the ladder block,
   `POST /leagues/{league_id}/settings` (full document replacement). Optionally
   archive Qualifiers / side divisions that are not in the ladder document.
6. **Enable** — POST settings again with `ladder.enabled: true` (still paused).
7. **Unpause** — `POST …/rounds-paused` with `{"paused": false}`.
8. **Prove one cycle** — `POST /leagues/{league_id}/trigger-round`. Confirm the
   Temporal parent `ladder-{league_id}` and a Competition `RoundWorkflow` child,
   a frozen episode plan, episode execution, and one Elo / score leaderboard
   update.

### Minimal Competition-only ladder sketch

Recommended defaults used in recent cutovers: Elo with `k_factor: 16`,
`min_episodes_per_entrant: 1`, Competition-only topology, fresh standings.

```json
{
  "ladder": {
    "enabled": false,
    "scheduler": {
      "strategy": "swiss_neighbor",
      "insufficient_players": "multiple_seats",
      "min_episodes_per_entrant": 1
    },
    "fulfillment": {
      "allowed_failures": 0.05,
      "retry_times": 2
    },
    "ranking": {
      "algorithm": "elo",
      "initial_rating": 1500.0,
      "k_factor": 16.0,
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

Replace `division_id` with the live Competition division. Keep `enabled: false`
until after the seed ownership flip.

## Choosing a seating strategy

Platform ladder seats **one champion policy version per player** per division
round. Benched competing versions do not seat. When champions < seat count,
pick one ladder-wide `insufficient_players` mode: `multiple_seats` (duplicate
real policies into filler-marked seats; no credit on duplicates),
`filler_policy` (league filler versions), or `do_not_run`.

| Strategy | Use when | Notes |
| --- | --- | --- |
| `swiss_neighbor` | Fixed-seat FFA; want close skill neighbors | Default for most FFA cutovers. Pair with Elo. Optional `neighbor_window` (default 1). |
| `round_robin` / `balanced_rotation` / `random_fill` | Fixed-seat FFA with different volume / coverage goals | `num_episodes` is exact for `balanced_rotation` / `random_fill`; omit to derive. |
| `team_pair` | Exactly **two** clone-filled teams (CTF, Cogtank) | Even seat count; credit one seat per team. Do **not** use for 4+ team maps. |
| `team_n` | N-team clone matchups (Four Score: `team_count: 4`) | Generalizes `team_pair`. `team_count` must divide seat count. |
| `variable_seat` | Per-episode seat count in `[min, max]` (Nightshift) | Requires coworld config that accepts the seat range; often pairs with `score` ranking. |
| `scaling_roster` | Largest legal headcount rung for the roster (Muster) | Prefer `score` with `standing_aggregation: max` for ATH / glory boards. |
| `clone_fill` | Full self-play: one champion fills every seat (Tribal Village) | Aggregates clone seat scores into one subject score per episode. |

Container seating YAML (`mmr_neighbors`, `team_blocks`, etc.) does not map 1:1.
Re-derive volume from roster size, seat count, and desired appearances per
champion (`min_episodes_per_entrant` is the usual lever for
`swiss_neighbor` / `round_robin`).

## Choosing ranking: `elo` vs `score`

| Algorithm | Prefer when |
| --- | --- |
| `elo` (default) | Relative skill / head-to-head; 0–1 or comparable numeric episode scores. Recent cutovers use `k_factor: 16`, `round_scoring_rule: mean`, `initial_rating: 1500`. |
| `score` | Continuous product boards players already understand (cash, hearts, session points, glory). Configure `round_scoring_rule`, `standing_aggregation` (`ewma` / `mean` / `max`), and `half_life_hours` when using EWMA. |

Container OpenSkill / EWMA standings do **not** carry over automatically. Prefer
fresh standings unless a separately reviewed one-off migration exists.

## When not to cut over yet

Do **not** migrate:

- **WoW** and **Proxywar** — special runtimes outside the normal seeded ladder
  path.
- Leagues whose fairness depends on a seating / ranking shape the platform
  cannot express yet for that coworld (wrong seat count, wrong team arity, or a
  board that must stay score-sorted while you only enable Elo).
- Daily / `commissioner_key=auto` leagues that are not normal seeded coworld
  ladders.

Do not paper over a four-team game with `team_pair`, or a variable-seat game
with a fixed FFA strategy — those recreations are product bugs, not cutovers.

## Behavior changes to expect

- Roster size drops from “every competing version” to “one champion per player”.
- Qualifiers are not ladder topology. Optional platform qualification is a
  ladder-wide self-play gate in `settings.ladder.qualification`; omit it to
  admit placed submissions straight into Competition.
- After soak, unused per-league commissioner Deployments can be scaled down.
  Do not delete the Coworld’s commissioner runnable from the manifest solely
  because this league moved — ownership is the seed override, not the absence
  of an image.

## Rollback sketch

1. Pause the league.
2. Let in-flight Temporal `RoundWorkflow` children settle.
3. Set `ladder.enabled: false` via settings POST (full document).
4. PATCH seed overrides **without** `commissioner_key` (or with
   `"commissioner_key": "container"`), re-including every other override.
   Reconcile restores container ownership and regenerates `commissioner_config`
   from the seed template.
5. Unpause only when the container commissioner is the intended owner again.

Fresh platform ratings written during the brief platform window will not
reconstruct prior container standings.

## See also

- [Commissioner role (container WebSocket contract)](roles/COMMISSIONER.md)
- Softmax internal migrate runbook (private Metta):
  `docs/ai/onboarding/services/coworlds/migrate-to-platform-commissioner.md`
- Softmax internal ladder matching / ranking extensions:
  `docs/specs/0072-ladder-matching-ranking-extensions.md`
