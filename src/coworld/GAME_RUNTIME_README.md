# Coworld Game Runtime Contract

This is the canonical contract for Coworld game containers. Player authors usually only need the player protocol linked
from a Coworld manifest; game authors need this file.

A Coworld episode has one game container and one policy/player container per slot. The runner starts the game, gives it
a config, starts the policy containers, records logs, and collects results and replay artifacts. The game owns the
rules. Policies connect over websocket and choose actions.

The public v2 tournament system is container-first: games are containers, submitted policies are containers, and the
manifest describes how those containers fit together into a Coworld episode.

## Manifest Fields

The `game` object in `coworld_manifest.json` describes the game container:

- `name`, `version`, `description`, and `owner`
- `runnable`: Docker image, optional command, and public environment variables
- `config_schema`: JSON Schema for the runtime game config
- `results_schema`: JSON Schema for the final results file
- `protocols.player`: player websocket protocol docs
- `protocols.global`: live viewer websocket protocol docs

Protocol docs are document objects:

```json
{ "type": "uri", "value": "https://example.com/player_protocol.md" }
```

Use `type: "uri"` for public HTTP(S) docs and `type: "text"` only for deliberately inline docs.

## Player Slots

The game config schema must require a `tokens` field. It must be a string array with equal `minItems` and `maxItems`.
That fixed length is the number of player slots.

Coworld-authored configs, variants, and certification fixtures do not include `tokens`. The runner creates fresh tokens
for each episode and injects them into the concrete runtime config.

The game must reject a `/player` websocket connection when the slot/token pair is not valid for that episode.

## Rollout Mode

For a normal episode, the runner starts the game with:

```bash
COGAME_CONFIG_URI=...
COGAME_RESULTS_URI=...
COGAME_SAVE_REPLAY_URI=...
COGAME_LOG_URI=...           # optional
```

The game must support `file://` URIs. Hosted runners may use other writable URI schemes when the game supports them.

If `COGAME_LOG_URI` is set, the game should POST log lines to that URL (plain text, one or more newline-separated
lines per request). If it is unset, the game must skip log posting. In either case, the container is free to log to
stdout/stderr as normal — these channels are independent.

In rollout mode, the game listens on `0.0.0.0:8080` and exposes:

- `GET /healthz`
- `GET /clients/player?slot=0&token=...&...`
- `WEBSOCKET /player?slot=0&token=...&...`
- `GET /clients/global`
- `WEBSOCKET /global`

`GET /healthz` returns 200 when the game is ready.

`GET /clients/player` serves a browser client for one slot. `GET /clients/global` serves a live viewer.

The served browser clients read the complete page query string before opening their websocket. If the query contains
`address`, the client uses that value as the full websocket URL after converting `http` or `https` to `ws` or `wss`; it
must not merge other page query params into that URL. Otherwise, the client derives the websocket URL by replacing
`/clients/player` with `/player`, or `/clients/global` with `/global`, and preserving the page query params such as
`slot`, `token`, and game-owned params.

For example, `/clients/player?slot=0&token=abc&role=scout` should open `/player?slot=0&token=abc&role=scout`. A hosted
proxy may instead serve `/clients/player?address=wss://example.com/player?slot=0&token=abc`.

The `/global` websocket must support late viewers. A viewer that joins after the episode starts should receive enough
state to render from that point forward.

The `/player` websocket must allow the same slot to reconnect with the same token while the episode is still running.
The slot's game state survives disconnects. During a disconnect, the game may use no-op actions or another documented
behavior.

Games may expose local-only admin controls by convention:

- `GET /clients/admin`
- `WEBSOCKET /admin?...`

The admin route is game-owned. The platform must not expose `/admin` in production.

## Replay Mode

For replay viewing, the runner starts or reuses the same game image with:

```bash
COGAME_REPLAY_SERVER=1
```

In replay mode, the game listens on `0.0.0.0:8080` and exposes:

- `GET /healthz`
- `GET /clients/replay?uri=<uri>`
- `WEBSOCKET /replay?uri=<uri>`

`GET /clients/replay?uri=<uri>` serves a browser replay viewer. The served client opens `/replay?uri=<uri>`. The game
loads the replay artifact and handles game-owned replay controls such as start, stop, seek, or speed changes.

The replay artifact format and replay websocket protocol are game-owned.

## Episode Lifecycle

1. The runner receives a job with the manifest, game config, players, and artifact output URIs.
2. The runner generates one token per player slot.
3. The runner writes the concrete game config, including `tokens`.
4. The runner starts the game container with config, result, and replay URIs.
5. The game reads its config and starts listening on port 8080.
6. The runner waits for `GET /healthz` to return 200.
7. The runner starts one player container per slot.
8. Each player gets `COGAMES_ENGINE_WS_URL=ws://<engine-host>/player?slot=<slot>&token=<token>` and,
   optionally, `COGAME_LOG_URI=...` with the same posting contract as the game.
9. Players connect to `/player` and send game-specific actions.
10. Viewers may connect to `/global`.
11. The game runs until the episode ends.
12. The game writes results to `COGAME_RESULTS_URI`.
13. The game writes a replay to `COGAME_SAVE_REPLAY_URI`.
14. The runner validates results against `results_schema` and stores results, replay, and logs.

The final results file must match `game.results_schema`. It must include `scores`, one number per player slot, and may
include extra game-specific fields declared by the schema.

## Certification

Coworld certification turns the manifest's `certification` fixture into one local episode. It runs the game and bundled
player images, checks the HTTP routes, verifies that bad player tokens are rejected, validates final results, and checks
that the replay viewer can start.
