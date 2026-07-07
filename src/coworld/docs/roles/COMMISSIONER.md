# Commissioner Role

**Status:** live

## What it does

The commissioner role decides the structure of a league: when new rounds should be created for each division, which
episodes get scheduled in each round, which policy versions play in each episode and in which slots, and how policies
move between divisions based on results. Hosted leagues invoke the selected commissioner runnable in two phases: a
league scheduling phase that returns zero or more round specs, and a per-round execution phase that drives the episodes
for one persisted round.

A commissioner is a WebSocket service container, consistent with how games and policies communicate. During league
scheduling, the platform asks it whether any division should get a new round. During round execution, it schedules
episodes incrementally, receives results and failures as they complete, can schedule additional episodes in response to
those episode outcomes, and signals when the round is done. Commissioner behavior comes from the runnable selected by
the league's `commissioner_config.commissioner_runnable_id`; the runnable may rely on its image entrypoint, or may
provide optional `run` and public-only `env` overrides in the manifest.

The commissioner is a black box from the platform's perspective — the platform doesn't know or care whether it's doing
round-robin, elimination, Swiss, or something exotic. The platform just executes the episodes the commissioner asks for
and streams results back.

## Where it lives in the manifest

`manifest.commissioner[]`, with `type: "commissioner"` on every entry. The section is optional in the schema, but hosted
league scheduling requires the league's `commissioner_config.commissioner_runnable_id`, and that value must match one
`manifest.commissioner[].id`. See [`COWORLD_MANIFEST.md`](../COWORLD_MANIFEST.md) for the full runnable shape.

Runnable `env` values are public configuration only. Secrets, credentials, private league data, and policy credentials
do not belong in the manifest or container environment; the platform sends scoped round context over the WebSocket
protocol.

### Manifest examples

Custom commissioner:

```json
{
  "commissioner": [
    {
      "type": "commissioner",
      "id": "my-commissioner",
      "name": "Swiss Tournament Commissioner",
      "description": "Swiss-system pairing with Elo-based seeding",
      "image": "my-swiss-commissioner:latest",
      "run": ["python", "commissioner.py"]
    }
  ]
}
```

Current image-entrypoint commissioner shape, used by Among Them:

```json
{
  "commissioner": [
    {
      "type": "commissioner",
      "id": "among-them-commissioner",
      "name": "Among Them Commissioner",
      "description": "Among Them container commissioner. It schedules episodes, computes rankings, moves players between divisions, and handles initial placement.",
      "image": "ghcr.io/metta-ai/commissioners-among-them-commissioner@sha256:<digest>"
    }
  ]
}
```

When `run` is omitted, the platform starts the image with its Docker entrypoint/default command. When `env` is omitted,
the public environment is empty. This is the current shape of the canonical Among Them commissioner manifest.

## Contract

Unlike post-episode analysis roles, the commissioner exposes a WebSocket server that the platform uses for both
league-level scheduling and per-round execution. The platform owns container startup, persistence, episode job dispatch,
and membership updates. The commissioner owns the league-specific decisions: whether a scheduling tick should create
rounds, how each round should be configured, which episodes to run inside a round, and what rankings or membership
events should result.

### Runtime contract

The commissioner container follows the same listen-on-8080 conventions as game containers:

- Listen on `0.0.0.0:8080`.
- Serve `GET /healthz` returning 200 when ready to accept a WebSocket connection.
- Serve `WEBSOCKET /round` — the main communication channel for the round.

The platform waits for `/healthz` to return 200, then connects to `/round`. All subsequent communication happens over
that WebSocket connection as JSON messages with a `"type"` field.

### League scheduling lifecycle

1. The platform round runner ticks for active container leagues.
2. Platform gathers the league, divisions, active memberships, and recent rounds, then resolves the selected
   commissioner runnable from the canonical Coworld manifest.
3. If the resolved commissioner runtime has not been made canonical for the league yet, platform starts the commissioner
   container and runs the league migration handshake before scheduling. The commissioner declares the canonical division
   set, may return policy membership events that move live memberships out of divisions it wants archived, and platform
   only records the commissioner migration version after that batch leaves no live memberships in archived divisions.
4. Platform starts the commissioner container, polls `/healthz` until ready (startup timeout, default 30s), connects to
   `WEBSOCKET /round`, and sends `schedule_rounds_request`.
5. Commissioner returns `schedule_rounds_response` with zero or more `RoundSpec` entries. An empty `rounds` array means
   no round is due on this tick.
6. Platform filters returned specs to known league divisions, enforces active-round and concurrency constraints,
   persists accepted `Round` rows, and starts per-round supervisors for them.

### Round execution lifecycle

1. For each persisted container round, platform starts the commissioner container.
2. Platform polls `/healthz` until ready, connects to `WEBSOCKET /round`, and sends `round_start` (round context:
   divisions, memberships, recent results, variants, optional state blob from the previous round).
3. Commissioner reads its state, sends `schedule_episodes` listing the episodes it wants to run.
4. Platform responds with `episodes_accepted` or `episodes_rejected`, dispatches valid episodes.
5. As episodes complete, platform sends `episode_result` or `episode_failed`.
6. Platform calls the commissioner's episode-completed hook for the result or failure; the commissioner may schedule
   more episodes, including retries or replacements after failures, or declare the round done.
7. Commissioner sends `round_complete` (per-division rankings, policy membership events, optional state blob) and exits.
8. Platform records results, applies policy membership events, stores commissioner state for the next round.
9. Container is terminated.

If the platform needs to cancel the round mid-stream, it sends `round_abort`. The commissioner is expected to exit
cleanly without sending `round_complete` in that case.

### Protocol message types

All commissioner protocol messages are JSON objects with a `"type"` discriminator. Pydantic models are defined in
[`commissioner/protocol.py`](../../commissioner/protocol.py).

#### Platform → commissioner

##### `schedule_rounds_request`

Sent during the league scheduling phase before a new round exists:

```json
{
  "type": "schedule_rounds_request",
  "league": {
    "id": "uuid_league",
    "commissioner_key": "container",
    "commissioner_config": { "commissioner_runnable_id": "among-them-commissioner" }
  },
  "divisions": [
    { "id": "uuid_open", "name": "open", "level": 0, "type": "competition" },
    { "id": "uuid_pro", "name": "pro", "level": 1, "type": "competition" }
  ],
  "active_memberships": [
    {
      "id": "uuid",
      "league_id": "uuid_league",
      "division_id": "uuid_open",
      "policy_version_id": "uuid",
      "player_id": "player_abc",
      "status": "competing",
      "substatus": "active",
      "is_champion": true
    }
  ],
  "recent_rounds": [
    {
      "id": "uuid_round",
      "public_id": "round_abc",
      "division_id": "uuid_open",
      "round_number": 4,
      "status": "completed",
      "round_config": {},
      "created_at": "2026-06-16T12:00:00Z",
      "started_at": "2026-06-16T12:05:00Z",
      "completed_at": "2026-06-16T12:10:00Z"
    }
  ]
}
```

The commissioner receives all divisions, active memberships, and recent rounds for the league. Platform-owned champion
state is carried by `is_champion`; `substatus` is commissioner-owned display and workflow state. The default scheduling
policy is to create rounds from `status="competing"` memberships with `is_champion=true`, report those memberships as
`substatus="active"`, and report non-champion competing memberships as `substatus="benched"`.

##### `league_migration_config_request`

Sent before scheduling when the selected commissioner runtime/config has not yet been made canonical for the league:

```json
{
  "type": "league_migration_config_request",
  "league": {
    "id": "uuid_league",
    "commissioner_key": "container",
    "commissioner_config": { "commissioner_runnable_id": "default-commissioner" }
  },
  "divisions": [{ "id": "uuid_daily", "name": "Daily", "level": 1, "type": "competition" }]
}
```

The commissioner responds with `league_migration_config_response`, declaring the canonical division names, levels,
types, and descriptions for this commissioner version. `previous_name` can be used to rename an existing division while
preserving its ID and history.

##### `league_migration_request`

Sent after the platform has created or renamed divisions from `league_migration_config_response`:

```json
{
  "type": "league_migration_request",
  "league": {
    "id": "uuid_league",
    "commissioner_key": "container",
    "commissioner_config": { "commissioner_runnable_id": "default-commissioner" }
  },
  "divisions": [{ "id": "uuid_competition", "name": "Competition", "level": 1, "type": "competition" }],
  "memberships": [
    {
      "id": "uuid_membership",
      "league_id": "uuid_league",
      "division_id": "uuid_daily",
      "policy_version_id": "uuid_policy_version",
      "status": "competing"
    }
  ]
}
```

The commissioner responds with `league_migration_response`, optionally returning policy membership events to move,
disqualify, or otherwise update memberships before obsolete divisions are archived. The platform applies the events in
one transaction, rejects events targeting divisions outside the canonical active set, and rejects the migration if any
live membership would remain in a division being archived.

##### `round_start`

Sent once after the WebSocket connects, providing the full round context. Competition rounds include all
`status="competing"` memberships for the division so the commissioner can decide whether to use only champions or a
custom entrant set.

```json
{
  "type": "round_start",
  "round_id": "uuid",
  "round_number": 5,
  "league": {
    "id": "uuid",
    "commissioner_config": { "schedule_interval_minutes": 10 }
  },
  "divisions": [
    { "id": "uuid_open", "name": "open", "level": 0 },
    { "id": "uuid_pro", "name": "pro", "level": 1 }
  ],
  "memberships": [
    {
      "id": "uuid",
      "league_id": "uuid_league",
      "division_id": "uuid_open",
      "policy_version_id": "uuid",
      "player_id": "player_abc",
      "status": "competing",
      "substatus": "active",
      "is_champion": true
    }
  ],
  "recent_results": [
    {
      "round_id": "uuid",
      "division_id": "uuid_open",
      "round_number": 4,
      "policy_version_id": "uuid",
      "rank": 1,
      "score": 0.85
    }
  ],
  "variants": [
    {
      "id": "arena_4p",
      "name": "4-Player Arena",
      "game_config": { "map_size": 32, "max_steps": 1000 }
    },
    {
      "id": "arena_2p",
      "name": "1v1 Arena",
      "game_config": { "map_size": 16, "max_steps": 500 }
    }
  ],
  "state": null
}
```

`is_champion` is read-only commissioner context. Commissioners must not attempt to set champions through membership
events; they may only move, activate, or disqualify memberships.

The commissioner receives all divisions in the league and all active memberships across them. It can schedule episodes
for any division and move policies between divisions via `policy_membership_events` in `round_complete`. Each membership
includes its `division_id` so the commissioner knows where each policy currently sits.

The `variants` array comes from the Coworld manifest's declared variants. The commissioner selects a variant by ID when
scheduling episodes, and the scheduled episode's `policy_version_ids` list defines that episode's player roster.

The `state` field contains the opaque blob returned by the commissioner's previous `round_complete` message (or `null`
for the first round). State is stored as a JSON column and limited to 10 MB.

##### `episodes_accepted`

Acknowledges a `schedule_episodes` request:

```json
{
  "type": "episodes_accepted",
  "request_ids": ["req_001", "req_002"]
}
```

##### `episodes_rejected`

Rejects invalid episode requests:

```json
{
  "type": "episodes_rejected",
  "request_ids": ["req_003"],
  "errors": { "req_003": "unknown policy_version_id: uuid_invalid" }
}
```

##### `episode_result`

Sent each time a scheduled episode completes:

```json
{
  "type": "episode_result",
  "request_id": "req_001",
  "scores": [
    { "policy_version_id": "uuid", "player_id": "player_abc", "score": 0.75 },
    { "policy_version_id": "uuid", "player_id": "player_xyz", "score": 0.25 }
  ],
  "game_results": {
    "scores": [0.75, 0.25],
    "territory_controlled": [0.6, 0.4],
    "resources_gathered": [120, 85]
  }
}
```

The `game_results` field contains the full results object conforming to the Coworld's `game.results_schema`. The
`scores` array is a convenience extraction from the game-written [results artifact](../artifacts/RESULTS.md), decomposed
per policy.

The commissioner does not receive or create episode bundles. It consumes round-level `episode_result` and
`episode_failed` messages; detailed per-episode artifacts are available through the
[`episode bundle`](../artifacts/EPISODE_BUNDLE.md) when a post-episode consumer asks for them.

##### `episode_failed`

Sent if an episode fails:

```json
{
  "type": "episode_failed",
  "request_id": "req_001",
  "error": "timeout after 300s"
}
```

##### `round_abort`

Sent when the platform needs to cancel the round (league disabled, deploy, admin action):

```json
{
  "type": "round_abort",
  "reason": "league disabled by admin"
}
```

On receiving `round_abort`, the commissioner should exit cleanly without sending `round_complete`. The platform marks
the round as cancelled.

#### Commissioner → platform

##### `league_migration_config_response`

Declare the canonical division set for this commissioner runtime/config:

```json
{
  "type": "league_migration_config_response",
  "divisions": [
    {
      "name": "Qualifiers",
      "level": -99,
      "type": "staging",
      "description": "Qualifier division for new submissions"
    },
    {
      "name": "Competition",
      "previous_name": "Daily",
      "level": 1,
      "type": "competition",
      "description": "Main competition ladder"
    }
  ]
}
```

Division names must be unique within the response. Existing divisions whose names are not in the response are archived
after the migration's policy membership events are applied and validated.

##### `league_migration_response`

Return membership events needed before obsolete divisions are archived:

```json
{
  "type": "league_migration_response",
  "policy_membership_events": [
    {
      "league_policy_membership_id": "uuid_membership",
      "from_division_id": "uuid_daily",
      "to_division_id": "uuid_competition",
      "status": "competing",
      "reason": "commissioner division migration"
    }
  ]
}
```

An empty response is valid only when no live memberships are left in divisions that the config response omits. The
platform records the migration version only after the event batch and archive validation succeed.

##### `schedule_rounds_response`

Return zero or more round specs for the current scheduling tick:

```json
{
  "type": "schedule_rounds_response",
  "rounds": [
    {
      "division_id": "uuid_open",
      "round_config": {
        "stages": [{ "label": "Round", "num_episodes": 8 }],
        "entrant_policy_version_ids": ["uuid_a", "uuid_b", "uuid_c", "uuid_d"]
      },
      "execution_backend": "dispatch",
      "notes": "daily open division round"
    }
  ]
}
```

The platform persists accepted specs as `Round` rows. It does not create a round when `rounds` is empty, when the
division is unknown, or when an active non-concurrent round already exists for that division.

##### `schedule_episodes`

Request episodes to run:

```json
{
  "type": "schedule_episodes",
  "episodes": [
    {
      "request_id": "req_001",
      "variant_id": "arena_4p",
      "policy_version_ids": ["uuid_a", "uuid_b", "uuid_c", "uuid_d"],
      "seed": 42,
      "tags": { "stage": "qualifying", "match": "1" }
    }
  ]
}
```

The `variant_id` references a variant declared in the Coworld manifest (passed in `round_start.variants`). The platform
uses this to resolve the game config and env config for the episode.

`policy_version_ids` is the ordered per-slot policy list — index `i` controls player slot `i` in the episode. Its length
is the episode's player count. Repeating a policy version is valid when one policy should control multiple slots.

The `request_id` is commissioner-generated and opaque to the platform. It's echoed back in `episode_result`,
`episode_failed`, `episodes_accepted`, and `episodes_rejected`.

The commissioner may send `schedule_episodes` more than once during a round. After each `episode_result` or
`episode_failed`, the platform invokes the commissioner's `on_episode_completed` hook. Any episodes returned by that
hook are scheduled before the round can complete, so a commissioner can replace failed episodes, retry with new seeds,
or adapt the remaining round schedule to observed results.

##### `round_complete`

Signal that the round is done:

```json
{
  "type": "round_complete",
  "results": [
    {
      "division_id": "uuid_open",
      "rankings": [
        { "policy_version_id": "uuid", "player_id": "player_abc", "rank": 1, "score": 0.85 },
        { "policy_version_id": "uuid", "player_id": "player_xyz", "rank": 2, "score": 0.6 }
      ]
    }
  ],
  "policy_membership_events": [
    {
      "league_policy_membership_id": "uuid",
      "from_division_id": "uuid_open",
      "to_division_id": "uuid_pro",
      "status": "competing",
      "reason": "promoted: won playoff"
    }
  ],
  "state": { "elo_ratings": { "player_abc": 1250, "player_xyz": 1180 } }
}
```

Results are grouped per division. The commissioner can produce rankings for multiple divisions in a single round.

`policy_membership_events` moves, activates, disqualifies, or annotates memberships. These are applied after the round
results are recorded. Legacy `membership_changes` responses are still accepted for older commissioners, but new
commissioners should emit `policy_membership_events`.

The complete output shape is documented as the [round decisions artifact](../artifacts/ROUND_DECISIONS.md). It is not an
episode artifact and is not part of the episode bundle.

The `state` field is an opaque JSON blob (max 10 MB) stored by the platform and passed back in the next round's
`round_start`. This lets a commissioner maintain ratings, bracket progress, Swiss pairings, etc. across rounds without
external storage.

#### Observability report (`observability`)

`round_complete` may carry an optional `observability` field: a `CommissionerRoundReport` (see
`coworld.commissioner.protocol`) that explains, in a game-agnostic schema, HOW the round was scored. The platform
persists it per round and the Observatory renders it so every scoring decision is inspectable end to end. It is additive
— a commissioner that omits it loses no behavior.

- `rule_id` / `rule_description`: the scoring rule in effect this round.
- `entrants[]`: per-entrant calculation. Beyond `outcome` / `score` / `steps` / `summary`, each entrant can carry the
  placement decision so the UI can show why an entrant moved: `decision` (e.g. `promoted`, `relegated`, `held`,
  `disqualified`, `ranked`), `from_division` / `to_division` (human names), and `reason_detail` (long-form reason).
- `render_html` (optional): self-contained HTML the commissioner authors to render its OWN view of the round — a
  game-specific standings table, MMR board, bracket, etc. — in place of the platform's generic structured view. The
  platform embeds it in a sandboxed, **script-disabled** iframe under a strict CSP, so it MUST obey the safe-render
  profile in [../artifacts/RENDER.md](../artifacts/RENDER.md): no scripts or event handlers, no external resource loads
  (inline `data:` / same-document only), no embedding or navigation sinks. Validate authored HTML with
  `coworld.report.assert_safe_render_html` (the same check `coworld certify` applies to reporter renders).

### State persistence

The `round_complete` `state` blob is passed back in the next round's `round_start.state`. The blob is opaque to the
platform — it never inspects or modifies the contents. State is stored as a JSON column and limited to 10 MB; the
platform rejects `round_complete` if `state` exceeds this limit (the round still succeeds, but state is not persisted
and a warning is logged).

### Health and liveness

The platform monitors commissioner health via:

- **`/healthz`** — polled before WebSocket connect (startup probe). If it does not return 200 before the startup
  timeout, the platform fails the round.
- **WebSocket ping/pong** — standard WebSocket protocol-level pings. If the commissioner stops responding to pings
  within a timeout (default 30s), the platform assumes it's deadlocked and terminates.

### Timeout and failure

- Container has a configurable max lifetime (default 10 minutes).
- If the container crashes or `/healthz` fails, the round is marked failed.
- If the WebSocket disconnects without `round_complete`, the round is marked failed.
- If WebSocket pings go unacknowledged for 30s, the container is terminated and the round fails.
- On `round_abort`, the commissioner exits cleanly; the round is marked cancelled (not failed).
- Failed and cancelled rounds do not produce rankings or policy membership events.

## Variant resolution

The v2 tournament surface is Coworld-native. A `Game` points at a Coworld name, and runtime scheduling resolves the
latest uploaded Coworld manifest for that name:

1. The Coworld manifest declares all available variants up front.
2. The platform selects the manifest's first variant for default v2 rounds.
3. The selected variant is materialized as an idempotent env-config row keyed by the resolved Coworld payload hash.
4. Rounds store scheduling config only; pools point at the env-config row.
5. Episode dispatch stores the resolved `coworld_id` and variant `game_config` directly on the request.
6. The number of agents is validated from the Coworld manifest game configs.

The commissioner never sees internal IDs like `env_config_id` or `mod_id`.

## Round scheduling

The platform owns the scheduling loop, round persistence, duplicate-active-round prevention, episode dispatch, and final
application of results and membership events. For container leagues, the commissioner owns the decision to return zero
or more round specs during that loop. A scheduling tick that returns an empty `schedule_rounds_response.rounds` list
means the commissioner decided no round is due.

`commissioner_config.commissioner_runnable_id` selects the commissioner runnable. Other values in `commissioner_config`
are platform context, not an override for a config-driven commissioner image; reusable `ruleset_strategy` commissioners
read their round cadence and structure from the YAML config baked into the image.

## League creation on deploy

When a Coworld with a commissioner is deployed:

1. Platform creates a `League` with `commissioner_key = "container"` and stores the Coworld release reference. If
   `commissioner_config.commissioner_runnable_id` is omitted or does not match a `manifest.commissioner[].id`, container
   scheduling fails before a round is created.
2. On the first scheduling tick for a new commissioner runtime/config, the platform asks the selected commissioner to
   declare the canonical division set and migration membership events.
3. The platform creates, renames, or archives divisions according to that migration, then records the commissioner
   migration version so the same migration is not repeated.
4. The round runner periodically asks the selected commissioner to schedule rounds with `schedule_rounds_request`.
5. For each accepted `RoundSpec`, the platform persists a round, starts a per-round commissioner container, and drives
   the `round_start`/episode/`round_complete` protocol.

## Manifest-selected commissioner

Commissioners are selected the same way regardless of whether they are game-specific or reusable: set
`commissioner_config.commissioner_runnable_id` to a `manifest.commissioner[].id`. The image, optional command, and
public environment all come from the uploaded Coworld manifest, so a league cutover must verify that the canonical
manifest points at the intended pinned commissioner image and any required `run`/`env` values.

Current examples include:

- Among Them: `id: "among-them-commissioner"` with image
  `ghcr.io/metta-ai/commissioners-among-them-commissioner@sha256:<digest>`.
- Reusable default commissioner: `id: "default-commissioner"` with image
  `ghcr.io/metta-ai/commissioners-default:latest`.

Prefer the mutable `:latest` tag in your source (`compose.yaml` / `commissioner.Dockerfile`), like the canonical worlds
(paintarena, tribal_village, ...) do. `coworld build --resolve-mutable-images` resolves `:latest` to the intended
immutable digest **at upload time** and writes that digest into the uploaded manifest, so each upload picks up the
newest published commissioner while the runner still gets an exact, pinned image. Hardcoding a digest in source instead
freezes the game on whatever was current when the digest was written, which is how coworlds silently ran a months-stale
commissioner.

## The reusable config-driven commissioner (`ruleset_strategy`)

Most Coworlds do not write their own commissioner. They reuse the **config-driven `ruleset_strategy` commissioner**
(images `ghcr.io/metta-ai/commissioners-*`, source
[`Metta-AI/coworld-tools/commissioners`](https://github.com/Metta-AI/coworld-tools/tree/main/commissioners)). Its entire
behavior — how many episodes a round runs, how entrants fill slots, how policies are promoted/disqualified — comes from
a **YAML config file baked into the image**.

The config is selected by a runtime environment variable the commissioner reads at startup:

- **`RULESET_STRATEGY_CONFIG_NAME`** — the name of a config **bundled in the image** (`default`, `among_them`,
  `cogs_vs_clips`, `four_score`, `cue_n_woo`, `proxywar`). Must be a bundled name; the per-config images are built with
  this baked to a build-arg default.
- **`RULESET_STRATEGY_CONFIG_PATH`** — an absolute path to **any** YAML file in the image. If set, it overrides
  `_CONFIG_NAME`. This is the hook for a game-specific config.

> **The config-driven commissioner does not read `league.commissioner_config` for scheduling.** That backend field is a
> platform wire artifact and may hold legacy data. The schedule comes entirely from the baked YAML — so you cannot
> change round behavior by editing the league row / backend seed; you change the **image's config**.

### What the config controls (rounds, seating, coverage)

`defaults.stage` sets the per-round episode budget. The number of episodes a Competition round runs is:

```
episode_count = stage.episodes                                              # when min_episodes_per_entrant is unset
              = max(stage.episodes,
                    ceil(num_entrants * min_episodes_per_entrant / num_agents))   # when it is set
```

where `num_agents` is the player count the commissioner chooses for each scheduled episode.

`defaults.seating` decides which entrants fill the slots in each episode `job_index` of the round:

- **`baseline_window`** (the `default` config's choice): a sliding window with
  `offset = job_index * num_agents (mod num_entrants)`. It rotates every episode, so across enough episodes every
  entrant is seated.
- **`rolling_window`**: window `[(job_index + seat) % num_entrants]` — rotates by one entrant per episode.
- **`team_blocks`** / **`leaderboard_neighbors`**: team-structured and skill-adjacent pairings.

#### Gotcha: low-player-count games starve entrants at `episodes: 1`

This bit cognames. A round with `episodes: 1` runs exactly one episode, which seats only `num_agents` entrants. For a
**multi-player** game that seats everyone (e.g. 4 entrants in one 4-player episode), so `episodes: 1` is fine. But for a
**low-player-count** game (e.g. 2-player) with **more than `num_agents` entrants**, one episode seats only the first
window; with `baseline_window` the same top-ranked entrants play every round and the rest are **never scheduled** — 0
episodes, 0 score, indefinitely.

Fix it by raising coverage so every entrant is seated each round:

- **`min_episodes_per_entrant`** is the scaling knob — it forces `ceil(num_entrants * k / num_agents)` episodes, so each
  entrant is seated ~`k` times and coverage grows automatically as the field grows. This is what the low-player-count
  leagues use: `cogs_vs_clips` = 8, `four_score` = 20, `among_them` = 100.
- Or a flat **`episodes: N`** large enough to rotate through all entrants (simpler, but fixed — it does not scale as
  champions join).

## Customizing round scheduling for your game

Three options, cheapest first:

1. **Reuse a bundled config** — point your manifest commissioner at the matching prebuilt image (e.g.
   `commissioners-cogs-vs-clips`). Only works if that config's rules already fit your game.
2. **Bundled config via manifest `env`** — set `RULESET_STRATEGY_CONFIG_NAME` to a bundled config name in the
   commissioner runnable's `env`. The platform `CoworldRunnableSpec` (`types.py`) supports a public `env` map on every
   runnable for exactly this. (Limitation: the **cogweb** manifest mirror's `CommissionerRunnable` does not yet expose
   `env` — only `image` and `run` — so cogweb games can't use this path until the mirror adds it. Use option 3.)
3. **Your own config, no shared-repo change** (recommended for custom scheduling) — bake your config into a downstream
   image and have your own Coworld build it:

   ```dockerfile
   # my-game/coworld/commissioner.Dockerfile
   FROM ghcr.io/metta-ai/commissioners-default:latest
   COPY my-commissioner.yaml /config/my-commissioner.yaml
   ENV RULESET_STRATEGY_CONFIG_PATH=/config/my-commissioner.yaml
   ```

   ```yaml
   # my-game/coworld/compose.yaml — the build maps service `commissioner` to {{COMMISSIONER_IMAGE}};
   # `coworld build` builds it and upload pushes it to the registry like the game image.
   services:
     commissioner:
       image: coworld-my-game-commissioner:latest
       platform: linux/amd64
       build:
         context: .
         dockerfile: commissioner.Dockerfile
   ```

   This keeps your scheduling config in your own repo instead of editing the shared `coworld-tools` configs. **Build
   `FROM …commissioners-default:latest`** so each build picks up the newest published commissioner;
   `coworld build --resolve-mutable-images` resolves the tag to an immutable digest at upload time, so the uploaded
   image is still exactly pinned. (The build/upload runs on linux/amd64 — where the `:latest` manifest list pulls fine —
   so the old arm64 caveat about pinning a platform-specific digest no longer applies on the build host.) cognames is
   the in-tree reference for this:
   `games/cognames/coworld/{cognames-commissioner.yaml,commissioner.Dockerfile,compose.yaml}`.

## How it fits with other roles

The commissioner sits at the top of the league control loop. It tells the platform which episodes to run; the platform's
game runner dispatches those episodes (with the requested policy versions in the requested slots); the game runnable
produces episode results; the platform routes those results back to the commissioner as `episode_result` or
`episode_failed` messages; the commissioner may respond by scheduling more episodes through its `on_episode_completed`
hook; and the commissioner eventually closes the round with [round decisions](../artifacts/ROUND_DECISIONS.md).

Unlike grader, diagnoser, and optimizer — all of which consume _individual_ episode evidence after episodes finish — the
commissioner consumes a stream of episode results in aggregate during a round and emits round-level decisions. The
[reporter](REPORTER.md) (v2, spec 0061) is likewise run-scoped rather than round-scoped: a submitted Wasm program the
platform instantiates per run, which reads evidence through its tool belt and emits typed output parts rather than
round decisions.

See [`README.md`](../README.md) for the full artifact and control-flow diagram.

## Implementation status

The protocol message models are live in [`commissioner/protocol.py`](../../commissioner/protocol.py). The platform's
container commissioner path resolves the selected runnable from the canonical Coworld manifest, starts a commissioner
container for `schedule_rounds_request`, persists accepted round specs, then starts per-round commissioner containers,
connects to `/round`, dispatches requested episode jobs, streams results or failures back to the commissioner, and
persists rankings, membership changes, and the opaque state blob.

The hosted backend no longer runs in-process commissioners. Leagues whose `commissioner_key` is not `container` are not
scheduled by the Coworld round runner.

Per-goal status:

| #   | Goal                                                                                             | Status                                                                    |
| --- | ------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------- |
| 1   | Commissioner containers drive rounds via WebSocket messaging                                     | Done                                                                      |
| 2   | Schedule episodes incrementally and receive results as they complete                             | Done                                                                      |
| 3   | Commissioner image and optional command/env come from the Coworld manifest                       | Done; verify the pinned image and `run`/`env` before daily-league cutover |
| 4   | Deploying a Coworld with a commissioner creates a league and begins scheduling                   | Done when seeding resolves a matching `manifest.commissioner[].id`        |
| 5   | Commissioner containers scoped to a single round (can be swapped between rounds)                 | Done                                                                      |
| 6   | Commissioners emit round rankings, scores, and policy membership events at the end of each round | Done                                                                      |
| 7   | Existing registered commissioners continue to work unchanged                                     | Removed; hosted scheduling is container-only                              |
| 8   | Commissioners declare canonical league divisions and migration events                            | Done                                                                      |

Container commissioner support is live in the backend. A league schedules only when its `commissioner_key` is
`container` and `commissioner_config.commissioner_runnable_id` resolves against the canonical Coworld manifest.

## Transition checklist

Before relying on an independent commissioner for a daily league:

1. Verify the canonical Coworld manifest has the intended `manifest.commissioner[].id`, pinned `image`, optional `run`,
   and public-only `env` values.
2. Verify the league row has `commissioner_key = "container"` and `commissioner_config.commissioner_runnable_id` equal
   to that manifest id.
3. Run or confirm the local cutover smoke that exercises the real `/round` WebSocket driver with the extracted
   commissioner implementation.
4. Run a read-only deployed smoke: inspect the target league, the latest commissioner-created round, episode results,
   round status, and commissioner pod/job logs for that round.
5. Confirm failed commissioner startup or WebSocket interruption marks only the current round failed.
6. Confirm `round_complete.state`, rankings, and membership changes are persisted as expected before treating the league
   as ready for unattended daily scheduling.

## Non-goals

- Commissioners that outlive a single round. State between rounds lives in the platform (carried via the opaque `state`
  blob).
- Custom episode execution. The platform runs the game engine; commissioners just say who plays.
- Custom scoring logic within episodes. Scores come from the game's `results_schema`.
- Replacing the v1 season/pool/match system.
- Max in-flight episode limits. Not currently part of the protocol; can be added later if needed.

## Resolved decisions

1. **Commissioner versioning.** Updating the Coworld's commissioner image takes effect next round automatically. The
   platform always pulls the latest image for the Coworld release.
2. **Division scope.** The commissioner receives all divisions, all memberships, and recent results across the entire
   league. A single round can schedule episodes across multiple divisions and produce per-division rankings.
3. **`/describe` endpoint.** Punted. No other runnables expose this. Commissioner description comes from the manifest's
   `description` field.
4. **State blob size.** Limited to 10 MB, stored as a JSON column. Platform rejects `round_complete` if `state` exceeds
   this limit (round still succeeds, state is not persisted, warning logged).
5. **Stuck commissioner detection.** Handled by the max-lifetime timeout (default 10 minutes). A per-message no-progress
   timeout can be added later if real cases require finer-grained detection.
6. **Dynamic division creation.** Commissioner runtimes can declare canonical divisions during the migration handshake
   for a new commissioner version/config. Per-round ad hoc division creation remains out of scope; schedule responses
   may only target known active league divisions.

## See Also

- [`Metta-AI/coworld-tools/commissioners`](https://github.com/Metta-AI/coworld-tools/tree/main/commissioners) — the
  reusable config-driven (`ruleset_strategy`) commissioner: per-game configs under `configs/`, the
  `episodes`/`min_episodes_per_entrant`/`seating` schema, and the image build matrix.
- [`REBUILDING_COWORLDS.md`](../REBUILDING_COWORLDS.md) — source-owner rules after the role repo consolidation.
- [`commissioner/protocol.py`](../../commissioner/protocol.py) — Pydantic models for every protocol message.
- [`artifacts/EPISODE_BUNDLE.md`](../artifacts/EPISODE_BUNDLE.md) — post-episode artifact package that commissioner
  protocol messages do not directly carry.
- [`artifacts/RESULTS.md`](../artifacts/RESULTS.md) — game-written episode results routed into `episode_result`.
- [`artifacts/ROUND_DECISIONS.md`](../artifacts/ROUND_DECISIONS.md) — commissioner output recorded by the platform.
- [`COWORLD_MANIFEST.md`](../COWORLD_MANIFEST.md) — manifest guide and generated-schema pointer.
- [`README.md`](../README.md) — role status framework, runnable conventions, and artifact flow.
- [`REPORTER.md`](REPORTER.md), [`GRADER.md`](GRADER.md), [`DIAGNOSER.md`](DIAGNOSER.md), [`OPTIMIZER.md`](OPTIMIZER.md)
  — sibling supporting runnables; all per-episode.
