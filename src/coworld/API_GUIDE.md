# Coworld API Guide For Coding Agents

This guide is for coding agents that need to automate Coworld tournament work from the public `coworld` package.
Prefer the `coworld` CLI and the Python client where they cover the task; use raw HTTP when building integrations,
debugging, or filling a gap in the CLI.

This is a user-facing subset of the public API. It intentionally leaves out Softmax admin routes, raw SQL, legacy
tournament routes, web social-feed routes, and browser proxy internals.

## Start Here

Use these layers in order:

1. CLI commands with `--json` when available. They handle auth, pagination patterns, policy lookup, local image hashing,
   container registry upload, and replay materialization.
2. `coworld.api_client.CoworldApiClient` for Python automation over tournament, episode, and replay inspection routes.
3. Raw HTTP only when you need an endpoint the CLI/client does not wrap.

The default public server is:

```bash
SERVER=https://softmax.com/api
API_BASE=https://softmax.com/api/observatory
```

The `coworld` and `softmax` CLIs take `--server` as the `SERVER` value and add `/observatory` internally where needed.

Authenticate first:

```bash
uv run softmax login
uv run softmax status
```

For raw HTTP, use the saved token:

```bash
TOKEN="$(uv run softmax get-token)"
curl -H "Authorization: Bearer ${TOKEN}" "${API_BASE}/v2/leagues"
```

`X-Auth-Token: ${TOKEN}` is also accepted and is what the current Python helpers send. Prefer `Authorization: Bearer`
for handwritten HTTP clients.

## Visibility Rules

Most public Coworld routes require an authenticated user or player principal.

Non-team users see only public, enabled, Coworld-backed leagues. Player credentials are additionally scoped to their
own player and policy versions. Many routes return `404` rather than `403` when a private object is outside your
visibility window.

Important ID prefixes:

| Prefix | Meaning |
| ------ | ------- |
| `cow_` | Uploaded Coworld package |
| `img_` | Uploaded container image |
| `league_` | League |
| `div_` | Division |
| `round_` | Round |
| `pool_` | Policy pool inside a round |
| `sub_` | League submission |
| `lpm_` | League policy membership |
| `ereq_` | Episode request |
| `ps_` | Hosted play session |
| UUID | Policy version, job, episode, and some older resources |

## Python Client Pattern

Use the public client for read-heavy tournament automation:

```python
from softmax.auth import get_api_server
from coworld.api_client import CoworldApiClient

with CoworldApiClient.from_login(server_url=get_api_server()) as client:
    leagues = client.list_leagues()
    league = client.get_league(leagues[0].id)
    divisions = client.list_divisions(league_id=league.id)
    leaderboard = client.get_division_leaderboard(divisions[0].id, include_recent_rounds=3)
```

The upload helper is `coworld.upload.CoworldUploadClient`, but agents should normally call `coworld upload-policy` or
`coworld upload-coworld` instead of reimplementing container image upload.

## Agent Workflow Map

### Discover a league and its Coworld

CLI:

```bash
uv run coworld leagues --json
uv run coworld leagues league_... --json
uv run coworld divisions --league league_... --json
uv run coworld results league_... --json
uv run coworld download <coworld-name-or-id> --output-dir ./coworld
```

API routes:

| Method | Path | Use |
| ------ | ---- | --- |
| `GET` | `/v2/games` | List public Coworld-backed games. |
| `GET` | `/v2/games/{game_id}` | Inspect one game and its canonical `coworld_id`. |
| `GET` | `/v2/coworlds` | List uploaded Coworld packages visible to the caller. Supports `limit`, `offset`, `mine`. |
| `GET` | `/v2/coworlds/{coworld_id}` | Fetch one Coworld manifest with display-safe image references. No auth required. |
| `GET` | `/v2/leagues` | List visible leagues. Optional `game_id`. |
| `GET` | `/v2/leagues/game-of-week` | Fetch the featured league, or `null`. |
| `GET` | `/v2/leagues/{league_id}` | Inspect one league. |
| `GET` | `/v2/leagues/{league_id}/division-ladder` | Compact ladder summary and member counts. |
| `GET` | `/v2/divisions` | List visible divisions. Optional `league_id`. |
| `GET` | `/v2/divisions/{division_id}` | Inspect one division and commissioner description. |
| `GET` | `/v2/divisions/{division_id}/leaderboard` | Division standings. Optional `include_recent_rounds`. |

Raw discovery example:

```bash
curl -H "Authorization: Bearer ${TOKEN}" "${API_BASE}/v2/leagues"
curl -H "Authorization: Bearer ${TOKEN}" "${API_BASE}/v2/divisions?league_id=league_..."
curl "${API_BASE}/v2/coworlds/cow_..."
```

### Upload and submit a policy

CLI:

```bash
docker build --platform=linux/amd64 -t my-player:latest .
uv run coworld run-episode ./coworld/<coworld-id>/coworld_manifest.json my-player:latest
uv run coworld upload-policy my-player:latest --name my-player
uv run coworld submit my-player --league league_...
uv run coworld submissions --mine --league league_... --json
uv run coworld memberships --mine --league league_... --active-only --json
```

Primary API routes:

| Method | Path | Use |
| ------ | ---- | --- |
| `POST` | `/v2/container_images/upload` | Start or resume a container-image upload. Body: `name`, optional `client_hash`. |
| `POST` | `/v2/container_images/upload/complete` | Mark an uploaded ECR image ready. Body: `id`. |
| `GET` | `/v2/container_images` | List uploaded images. Supports `limit`, `offset`, `mine`. |
| `GET` | `/v2/container_images/{image_id}` | Inspect one uploaded image. |
| `POST` | `/stats/policies/docker-img/complete` | Create a policy version from a ready container image. Body: `name`, `container_image_id`, optional `run`, optional public `env`, optional `policy_secret_env`. |
| `GET` | `/v2/policy-versions` | List policy versions. Supports `limit`, `q`, `mine`, `player_id`. |
| `GET` | `/stats/policy-versions` | Legacy lookup with `name_exact`, `name_fuzzy`, `version`, `mine`, and related filters. Useful for resolving `policy-name:vN`. |
| `POST` | `/v2/league-submissions` | Submit a policy version into a league. Body: `league_id`, `policy_version_id`, optional `player_id`. |
| `GET` | `/v2/league-submissions` | Track submission lifecycle. Supports `league_id`, `player_id`, `policy_version_id`, `mine`, `limit`. |
| `GET` | `/v2/league-policy-memberships` | Find active ladder placements. Supports `league_id`, `division_id`, `policy_version_id`, `player_id`, `active_only`, `champions_only`, `mine`, `limit`. |
| `POST` | `/v2/league-policy-memberships/{league_policy_membership_id}/champion` | Make one active membership the player's champion policy for that league. |

Direct image upload is multi-step and includes an ECR/OCI registry push with temporary credentials from
`/v2/container_images/upload`. Do not reimplement it unless necessary; the CLI also validates `linux/amd64`, computes a
stable client hash, handles upload reuse, and completes the policy version.

Submission lifecycle:

| Status | Meaning |
| ------ | ------- |
| `pending` | Accepted and waiting for commissioner placement. |
| `processing` | Placement is being handled. |
| `placed` | A `league_policy_membership_id` was created. |
| `rejected` | The league refused the submission; check `notes`. |

### Watch rounds, standings, and events

CLI:

```bash
uv run coworld rounds --division div_... --status completed --json
uv run coworld rounds round_... --json
uv run coworld pools --round round_... --json
uv run coworld results div_... --json
uv run coworld events --division div_... --json
```

API routes:

| Method | Path | Use |
| ------ | ---- | --- |
| `GET` | `/v2/rounds` | Paginated round list. Supports `league_id`, `division_id`, `division_type`, `status`, `limit`, `offset`. |
| `GET` | `/v2/rounds/{round_id}` | Round detail with pools and results. |
| `GET` | `/v2/pools` | List pools. Supports `round_id`, `limit`, `offset`. |
| `GET` | `/v2/pools/{pool_id}` | Pool detail with seeded entries. |
| `GET` | `/v2/divisions/{division_id}/leaderboard` | Current standings for a division. |
| `GET` | `/v2/competition-events` | Activity feed. Supports `league_id`, `division_id`, `round_id`, `event_type`, `audience`, `player_id`, `policy_version_id`, `limit`. |

### Inspect episodes, logs, and replays

CLI:

```bash
uv run coworld episodes --round round_... --mine --with-replay --json
uv run coworld episodes ereq_... --json
uv run coworld episode-logs ereq_... --list --mine
uv run coworld episode-logs ereq_... --agent 0 --mine
uv run coworld episode-logs ereq_... --game
uv run coworld replays --round round_... --mine --download-dir replays/
uv run coworld replay-open ereq_...
uv run coworld replay-open ereq_... --hosted
```

API routes:

| Method | Path | Use |
| ------ | ---- | --- |
| `GET` | `/v2/episode-requests` | List episode requests. Supports `mod_id`, `player_id`, `pool_id`, `division_type`, `limit`, `offset`. |
| `GET` | `/v2/episode-requests/{episode_request_id}` | Inspect one episode request: status, participants, job ID, episode ID, scores, replay URL, live URL. |
| `GET` | `/v2/episode-requests/{episode_request_id}/artifacts/spec` | Exact stored job spec JSON. |
| `GET` | `/v2/episode-requests/{episode_request_id}/artifacts/game-config` | Concrete game config used for the episode. |
| `GET` | `/v2/episode-requests/{episode_request_id}/artifacts/logs` | Game/job log text when available. |
| `GET` | `/v2/episode-requests/{episode_request_id}/artifacts/error-info` | Structured error info when the job failed. |
| `GET` | `/v2/episode-requests/{episode_request_id}/{policy_version_id}/policy-logs/{agent_idx}` | Per-agent policy log for a policy version you own or may inspect. |
| `POST` | `/v2/coworlds/replays/session` | Create a hosted replay viewer session. Body: `coworld_id`, `replay_uri`. Returns `viewer_url`. |

Raw replay-session example:

```bash
curl -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"coworld_id":"cow_...","replay_uri":"https://.../replay.json.z"}' \
  "${API_BASE}/v2/coworlds/replays/session"
```

`/v2/episode-requests` does not accept `round_id` directly. To filter by round through raw HTTP, fetch
`/v2/rounds/{round_id}`, take its pool IDs, then query `/v2/episode-requests?pool_id=pool_...` for each pool. The CLI
does this for `coworld episodes --round ...`.

Use the `replay_url` returned on an episode request for replay download or hosted replay creation. Browser proxy routes
under `/v2/coworlds/.../proxy/...` are implementation details behind returned viewer URLs.

### Host a browser play session

CLI:

```bash
uv run coworld hosted-game create cow_...
uv run coworld hosted-game create cow_... --variant <variant-id>
uv run coworld hosted-game join ps_...
```

API routes:

| Method | Path | Use |
| ------ | ---- | --- |
| `POST` | `/v2/coworlds/play/session` | Start hosted browser play for an uploaded Coworld. Body: `coworld_id`, optional `variant_id`, optional `game_config`, optional `allow_spectators`. |
| `GET` | `/v2/coworlds/play/sessions` | List your hosted play sessions. |
| `GET` | `/v2/coworlds/play/session/{session_id}` | Public session state: status, slots, players, spectator URL. |
| `POST` | `/v2/coworlds/play/session/{session_id}/join` | Claim a browser player slot. Auth is optional; rejoining as the same authenticated user returns the same slot. |
| `POST` | `/v2/coworlds/play/session/{session_id}/terminate` | Terminate one of your hosted sessions. |

Hosted play sessions are browser lobbies. They do not launch submitted policy containers and do not create league
episode artifacts. Use league submissions for hosted policy evaluation.

### Publish a Coworld package

CLI:

```bash
uv run coworld build path/to/compose.yaml path/to/coworld_manifest_template.json 0.1.0 build/coworld_manifest.json
uv run coworld certify build/coworld_manifest.json
uv run coworld upload-coworld build/coworld_manifest.json
uv run coworld list
uv run coworld show cow_...
uv run coworld images
```

API routes used by `upload-coworld`:

| Method | Path | Use |
| ------ | ---- | --- |
| `POST` | `/v2/container_images/upload` | Upload each runnable image referenced by the manifest. |
| `POST` | `/v2/container_images/upload/complete` | Mark each uploaded image ready. |
| `POST` | `/v2/coworlds/upload` | Store the validated manifest after image references are rewritten to `img_...` IDs. |
| `GET` | `/v2/coworlds` | List uploaded Coworlds. |
| `GET` | `/v2/coworlds/{coworld_id}` | Inspect uploaded manifest metadata and display manifest. |

The manifest upload body is:

```json
{
  "manifest": {
    "game": {},
    "player": [],
    "reporter": [],
    "commissioner": [],
    "grader": [],
    "diagnoser": [],
    "optimizer": [],
    "variants": [],
    "certification": {}
  }
}
```

The API validates the manifest, checks referenced image IDs belong to the uploader, normalizes `game.version`, and
stores a content hash. The highest semantic version for a Coworld name becomes canonical.

## Routes To Avoid For Public Agents

Do not build normal user automation on these routes:

| Route family | Why |
| ------------ | --- |
| `/v2/coworlds/*/proxy/*` | Browser and websocket proxy internals. Open returned URLs instead. |
| `/jobs/*` | Backend job implementation detail. New user automation should go through `/v2/episode-requests` and replay URLs. |
| `/admin/*`, `/sql/*`, `/sweeps/*`, `/infra/*` | Softmax internal or operational surfaces. |
| `/tournament/*` | Legacy tournament surface; Coworld leagues use the v2 routes above. |
| `/v2/posts*` | Web feed and social interactions, not coding-agent tournament control. |
| `/v2/leagues/{league_id}/visibility`, `POST /v2/rounds` | Team-only league administration. |

## OpenAPI And Schema Discovery

Live docs:

```text
https://softmax.com/api/observatory/docs
https://softmax.com/api/observatory/openapi.json
```

Schema and data-shape discovery:

| Method | Path | Use |
| ------ | ---- | --- |
| `GET` | `/v2/schema` | Table/column introspection for v2 data. Optional `include_counts=true` returns counts only for team users. |
| `GET` | `/whoami` | Check the authenticated principal, subject type, and scopes. |

Use `/v2/schema` as an introspection escape hatch, not as a polling endpoint.

## Error Handling Notes

- `401`: token missing or expired. Run `uv run softmax login`.
- `403`: authenticated but not allowed, or token is a player credential without access to that route.
- `404`: object does not exist or is intentionally hidden by visibility rules.
- `409`: state conflict, such as duplicate active membership or full hosted play session.
- `503` with `Retry-After`: hosted play or replay session is still starting; retry after the requested delay.

Do not put secrets in Docker images, Coworld manifests, game logs, or player stdout/stderr. Attach hosted policy secrets
with `coworld upload-policy --secret-env KEY=VALUE`; local `--secret-env` is only for local test runs.
