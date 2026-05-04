# Cogame Spec

`cogame` is the contract package for Cogame repositories: it defines the manifest schemas, container runtime API,
websocket endpoints, config/results formats, browser client requirements, and episode lifecycle a game must provide to
run on the CoGames platform.

Short version:

> Specs and schemas for defining, validating, and running containerized Cogames.

## Package Contract

At the base of a game package there must be a `cogame_manifest.json` file that adheres to `cogame_manifest_schema.json`; see that
schema for exact validation requirements.

The manifest contains:

- `name`, `version`, and `description`,
- `owner`: the game owner's contact email,
- `image_uri`: the game engine container image,
- `config_schema`: JSON Schema for the config file supplied to the container,
- `results_schema`: JSON Schema for the results file written by the container,
- `protocols.player`: documentation for the player websocket protocol,
- `protocols.global`: documentation for the global websocket protocol,
- `clients.player`: path to the static player browser client,
- `clients.global`: path to the static global browser client.

The `config_schema` must require `tokens`, one token per player slot, and may define additional game-specific
config fields. The `results_schema` must require `scores`, one scalar score per player slot, and may define additional
game-specific result fields.

## Container Contract

The container referenced by `image_uri` must implement the runtime contract below.

The runner supplies:

- `COGAME_CONFIG_PATH`: path to the config JSON file,
- `COGAME_RESULTS_PATH`: path where the game writes final results,
- `COGAME_SAVE_REPLAY_PATH`: optional path where the game writes a replay artifact.

The game container listens on `0.0.0.0:8080` and exposes:

- `GET /healthz`
- `/player?slot=0&token=...`
- `/global`

The `/global` endpoint must accept viewer connections after an episode has already started. A viewer that connects
mid-episode must receive enough state over the global protocol to render from its join point without requiring the
episode to restart.

The `/player` endpoint must allow a player to reconnect to the same slot with the same token while the episode is still
running. The slot's game state survives disconnects. During a disconnect, the game may advance that slot with no-op
actions or another documented disconnected-player behavior until the player reconnects.

Replay production is an open question. The current spec requires the game to write a replay artifact to
`COGAME_SAVE_REPLAY_PATH` when that environment variable is present. An alternative valid design is that the runner
consumes and records everything served on `/global` while the episode is rolling out, writes that stream to the replay
file, and replays it later by sending the recorded stream to a global viewer. In that design, the game container does
not need to produce a replay file itself.

## Coworld Contract

A Coworld references exactly one Cogame through `game.manifest_uri` in `coworld_manifest.json`. That URI points to a
`cogame_manifest.json` instance that validates against `cogame_manifest_schema.json`.

## Episode Config

The runner receives an episode request that adheres to `episode_request_schema.json`. It has the game config,
player container images and initial params, and output destinations.

## Episode Lifecycle

1. The runner receives episode config containing `game_config`, `players`, and artifact output URIs.
2. The runner generates a random string token for each player slot.
3. The runner writes game config JSON matching the manifest's `config_schema` to a file, replacing/inserting
   `tokens` with the generated tokens.
4. The runner starts the game engine container and supplies:
   - `COGAME_CONFIG_PATH`: path to the config JSON file,
   - `COGAME_RESULTS_PATH`: path where the game writes final results,
   - `COGAME_SAVE_REPLAY_PATH`: optional path where the game writes a replay artifact.
5. The runner records all stdout and stderr from the game engine.
6. The container boots and listens for HTTP and websocket traffic on `0.0.0.0:8080`.
7. The game engine exposes `GET /healthz`, which returns `200` when the container is ready to accept connections.
8. For each player, the runner:
   - decides which policy image corresponds to which slot,
   - starts one container per policy image,
   - supplies `COGAMES_ENGINE_WS_URL=/player?slot=<slot>&token=<token>&...` to the policy container,
   - appends each player's `initial_params` to that URL as query params.
9. The game rejects player connections whose `token` does not match the token for that slot.
10. Global viewers may connect before or during the episode through `/global`.
11. Players may disconnect and reconnect to the same slot with the same token.
12. The game engine progresses the game after each player connects.
13. When the game ends, it writes results to `COGAME_RESULTS_PATH`. The results file is JSON matching `results_schema`.
    If `COGAME_SAVE_REPLAY_PATH` is present, the game also writes a replay file there.
14. The runner uploads results, replay, and logs to the episode config output URIs.
