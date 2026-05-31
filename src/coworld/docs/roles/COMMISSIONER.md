# Commissioner Role

**Status:** contract defined, runtime pending

## What it does

The commissioner role decides the structure of a league: which episodes get scheduled in each round, which policy
versions play in each episode and in which slots, and how policies move between divisions based on results.
Commissioners run once per league round — the lifetime of a commissioner container session is exactly the lifetime of
one round, not one episode and not the whole league.

A commissioner is a long-lived container scoped to one round that communicates with the platform via WebSocket,
consistent with how games and policies communicate. It schedules episodes incrementally, receives results and failures
as they complete, can schedule additional episodes in response to those episode outcomes, and signals when the round is
done. Authors who don't need custom logic can use the platform-provided default commissioner configured via CLI flags.

The commissioner is a black box from the platform's perspective — the platform doesn't know or care whether it's doing
round-robin, elimination, Swiss, or something exotic. It just executes the episodes the commissioner asks for and
streams results back.

## Where it lives in the manifest

`manifest.commissioner[]`, with `type: "commissioner"` on every entry. The section is optional in the current schema,
but intended to become required once the container-driven commissioner runtime ships. Coworld leagues that do not select
a custom commissioner use the platform default commissioner image. Custom commissioners are selected by the league's
`commissioner_config.commissioner_runnable_id`, which must match one `manifest.commissioner[].id`. See
[`COWORLD_MANIFEST.md`](../COWORLD_MANIFEST.md) for the full runnable shape.

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

Future default commissioner with CLI configuration:

```json
{
  "commissioner": [
    {
      "type": "commissioner",
      "id": "default",
      "name": "Standard League Commissioner",
      "description": "Round-robin with percentile graduation",
      "image": "<default-commissioner-image>",
      "run": [
        "default-commissioner",
        "--round-robin",
        "--episodes-per-pair=3",
        "--graduation=percentile",
        "--promote-top-pct=10",
        "--relegate-bottom-pct=10"
      ]
    }
  ]
}
```

## Contract

Unlike reporter, grader, diagnoser, and optimizer (all per-episode), the commissioner is a **per-round** runnable that
exposes a WebSocket server. Once a round begins, the platform starts the commissioner container, connects to its
`/round` WebSocket, exchanges JSON protocol messages, and lets the container exit when the round completes.

### Runtime contract

The commissioner container follows the same listen-on-8080 conventions as game containers:

- Listen on `0.0.0.0:8080`.
- Serve `GET /healthz` returning 200 when ready to accept a WebSocket connection.
- Serve `WEBSOCKET /round` — the main communication channel for the round.

The platform waits for `/healthz` to return 200, then connects to `/round`. All subsequent communication happens over
that WebSocket connection as JSON messages with a `"type"` field.

### Round lifecycle

1. Platform's round-scheduling logic determines a new round is due (per the league's `commissioner_config`).
2. Platform starts the commissioner container.
3. Platform polls `/healthz` until ready (startup timeout, default 30s).
4. Platform connects to `WEBSOCKET /round` and sends `round_start` (round context: divisions, memberships, recent
   results, variants, optional state blob from the previous round).
5. Commissioner reads its state, sends `schedule_episodes` listing the episodes it wants to run.
6. Platform responds with `episodes_accepted` or `episodes_rejected`, dispatches valid episodes.
7. As episodes complete, platform sends `episode_result` or `episode_failed`.
8. Platform calls the commissioner's episode-completed hook for the result or failure; the commissioner may schedule
   more episodes, including retries or replacements after failures, or declare the round done.
9. Commissioner sends `round_complete` (per-division rankings, graduation changes, optional state blob) and exits.
10. Platform records results, applies graduation changes, stores commissioner state for the next round.
11. Container is terminated.

If the platform needs to cancel the round mid-stream, it sends `round_abort`. The commissioner is expected to exit
cleanly without sending `round_complete` in that case.

### Protocol message types

All commissioner protocol messages are JSON objects with a `"type"` discriminator. Pydantic models are defined in
[`commissioner/protocol.py`](../../commissioner/protocol.py).

#### Platform → commissioner

##### `round_start`

Sent once after the WebSocket connects, providing the full round context:

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
      "division_id": "uuid_open",
      "policy_version_id": "uuid",
      "player_id": "player_abc",
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
      "num_agents": 4,
      "game_config": { "tokens": ["", "", "", ""], "map_size": 32, "max_steps": 1000 }
    },
    {
      "id": "arena_2p",
      "name": "1v1 Arena",
      "num_agents": 2,
      "game_config": { "tokens": ["", ""], "map_size": 16, "max_steps": 500 }
    }
  ],
  "state": null
}
```

The commissioner receives all divisions in the league and all active memberships across them. It can schedule episodes
for any division and move policies between divisions via `graduation_changes` in `round_complete`. Each membership
includes its `division_id` so the commissioner knows where each policy currently sits.

The `variants` array comes from the Coworld manifest's declared variants, plus platform-derived `num_agents` metadata.
The number of agents is inferred from the Coworld `config_schema` token count and is included explicitly so
commissioner containers do not need to duplicate schema inspection. The commissioner selects a variant by ID when
scheduling episodes.

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
`scores` array is a convenience extraction from the game-written [results artifact](../artifacts/RESULTS.md),
decomposed per policy.

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

`policy_version_ids` is the ordered per-slot policy list — index `i` controls player slot `i` in the episode. Length
must match the variant's player count (the `tokens` array length declared in the Coworld's `game.config_schema`).
Repeating a policy version is valid when one policy should control multiple slots.

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
  "graduation_changes": [
    {
      "membership_id": "uuid",
      "to_division_id": "uuid_pro",
      "reason": "promoted: won playoff"
    }
  ],
  "state": { "elo_ratings": { "player_abc": 1250, "player_xyz": 1180 } }
}
```

Results are grouped per division. The commissioner can produce rankings for multiple divisions in a single round.

`graduation_changes` moves policies between divisions. These are applied after the round results are recorded.

The complete output shape is documented as the [round decisions artifact](../artifacts/ROUND_DECISIONS.md). It is not an
episode artifact and is not part of the episode bundle.

The `state` field is an opaque JSON blob (max 10 MB) stored by the platform and passed back in the next round's
`round_start`. This lets a commissioner maintain ratings, bracket progress, Swiss pairings, etc. across rounds without
external storage.

### State persistence

The `round_complete` `state` blob is passed back in the next round's `round_start.state`. The blob is opaque to the
platform — it never inspects or modifies the contents. State is stored as a JSON column and limited to 10 MB; the
platform rejects `round_complete` if `state` exceeds this limit (the round still succeeds, but state is not persisted
and a warning is logged).

### Health and liveness

The platform monitors commissioner health via:

- **`/healthz`** — polled before WebSocket connect (startup probe) and periodically during the round (liveness probe).
  If it stops returning 200, the platform terminates the container and fails the round.
- **WebSocket ping/pong** — standard WebSocket protocol-level pings. If the commissioner stops responding to pings
  within a timeout (default 30s), the platform assumes it's deadlocked and terminates.

### Timeout and failure

- Container has a configurable max lifetime (default 10 minutes).
- If the container crashes or `/healthz` fails, the round is marked failed.
- If the WebSocket disconnects without `round_complete`, the round is marked failed.
- If WebSocket pings go unacknowledged for 30s, the container is terminated and the round fails.
- On `round_abort`, the commissioner exits cleanly; the round is marked cancelled (not failed).
- Failed and cancelled rounds do not produce rankings or graduation changes.

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

The decision of when to start a new round remains platform-side. The league's `commissioner_config` specifies the
scheduling cadence and minimum champions — the same `RoundSchedulingConfig` fields used today. The commissioner
container only drives what happens _within_ a round.

## League creation on deploy

When a Coworld with a commissioner is deployed:

1. Platform creates a `League` with `commissioner_key = "container"` and stores the Coworld release reference. If
   `commissioner_config.commissioner_runnable_id` is omitted, the platform default commissioner is used; otherwise the
   value must match a `manifest.commissioner[].id`.
2. Platform creates default divisions (configurable in manifest, defaults to a single "open" division).
3. The round runner begins scheduling rounds per `commissioner_config`.
4. Each round, the platform starts the commissioner container and drives the WebSocket protocol.

## Default commissioner

The planned default commissioner image will implement the WebSocket protocol and provide common strategies via CLI
flags:

| Flag                      | Behavior                                   |
| ------------------------- | ------------------------------------------ |
| `--round-robin`           | Every pair plays N times                   |
| `--swiss`                 | Pair by similar score, N rounds            |
| `--elimination=single`    | Single-elimination bracket                 |
| `--elimination=double`    | Double-elimination bracket                 |
| `--episodes-per-pair=N`   | Matches per pairing                        |
| `--graduation=percentile` | Promote top N%, relegate bottom N%         |
| `--graduation=win-streak` | Promote after N consecutive top-K finishes |
| `--graduation=none`       | No promotion or relegation                 |
| `--promote-top-pct=N`     | Top N% promotes                            |
| `--relegate-bottom-pct=N` | Bottom N% relegates                        |

## How it fits with other roles

The commissioner sits at the top of the league control loop. It tells the platform which episodes to run; the platform's
game runner dispatches those episodes (with the requested policy versions in the requested slots); the game runnable
produces episode results; the platform routes those results back to the commissioner as `episode_result` or
`episode_failed` messages; the commissioner may respond by scheduling more episodes through its `on_episode_completed`
hook; and the commissioner eventually closes the round with [round decisions](../artifacts/ROUND_DECISIONS.md).

Unlike reporter, grader, diagnoser, and optimizer — all of which consume _individual_ episode evidence on demand after
episodes finish — the commissioner consumes a stream of episode results in aggregate during a round and emits
round-level decisions. It is the only supporting role besides game that holds a long-lived WebSocket contract with the
platform.

See [`README.md`](../README.md) for the full artifact and control-flow diagram.

## Implementation status

The protocol message models are live in [`commissioner/protocol.py`](../../commissioner/protocol.py). The platform's
existing commissioners (notably `AmongThemCommissioner` for the Among Them Daily league) speak this protocol in-process
— they implement the same `schedule_episodes` / `round_complete` shape directly in Python rather than going over a
WebSocket. See
[`AMONGTHEM_COMMISSIONER.md`](../../../../../../app_backend/src/metta/app_backend/v2/AMONGTHEM_COMMISSIONER.md) for the
in-process reference.

Per-goal status:

| #   | Goal                                                                                       | Status                                                                                             |
| --- | ------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------- |
| 1   | Commissioner containers drive rounds via WebSocket messaging                               | Pending — `/round` WS driver on the platform side not yet shipped                                  |
| 2   | Schedule episodes incrementally and receive results as they complete                       | Done in-process (`AmongThemCommissioner`); pending in container form                               |
| 3   | Default commissioner image covers common patterns via CLI config                           | Pending — image not yet built                                                                      |
| 4   | Deploying a Coworld with a commissioner creates a league and begins scheduling             | Partial — in-process commissioners drive Among Them Daily today; container-driven path not shipped |
| 5   | Commissioner containers scoped to a single round (can be swapped between rounds)           | Design fixed; runtime pending                                                                      |
| 6   | Commissioners emit round rankings, scores, and graduation changes at the end of each round | Done in-process; same pending in container form                                                    |
| 7   | Existing registered commissioners continue to work unchanged                               | Done                                                                                               |

Until the `/round` WebSocket driver and default commissioner image are built, `manifest.commissioner[]` entries are
declared but not actually invoked as containers; Coworld leagues run through the in-process Python commissioners on the
backend.

## Non-goals

- Commissioners that outlive a single round. State between rounds lives in the platform (carried via the opaque `state`
  blob).
- Custom episode execution. The platform runs the game engine; commissioners just say who plays.
- Custom scoring logic within episodes. Scores come from the game's `results_schema`.
- Replacing the v1 season/pool/match system. The container commissioner path lives alongside existing in-process
  commissioners; the pipeline supports both.
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
6. **Dynamic division creation.** No for v1. Division structure is fixed at Coworld deploy time. If dynamic divisions
   become a real requirement, they will be added in a separate spec.

## See Also

- [`commissioner/protocol.py`](../../commissioner/protocol.py) — Pydantic models for every protocol message.
- [`AMONGTHEM_COMMISSIONER.md`](../../../../../../app_backend/src/metta/app_backend/v2/AMONGTHEM_COMMISSIONER.md) —
  in-process AmongThem commissioner reference (backend doc).
- [`artifacts/EPISODE_BUNDLE.md`](../artifacts/EPISODE_BUNDLE.md) — post-episode artifact package that commissioner
  protocol messages do not directly carry.
- [`artifacts/RESULTS.md`](../artifacts/RESULTS.md) — game-written episode results routed into `episode_result`.
- [`artifacts/ROUND_DECISIONS.md`](../artifacts/ROUND_DECISIONS.md) — commissioner output recorded by the platform.
- [`COWORLD_MANIFEST.md`](../COWORLD_MANIFEST.md) — manifest guide and generated-schema pointer.
- [`README.md`](../README.md) — role status framework, runnable conventions, and artifact flow.
- [`REPORTER.md`](REPORTER.md), [`GRADER.md`](GRADER.md), [`DIAGNOSER.md`](DIAGNOSER.md), [`OPTIMIZER.md`](OPTIMIZER.md)
  — sibling supporting runnables; all per-episode.
