# Cogame Spec

`cogame` is the contract package for Cogame repositories: it defines the manifest schemas, container runtime API,
websocket endpoints, config/results formats, and episode lifecycle a game must provide to run on the CoGames platform.

Short version:

> Specs and schemas for defining, validating, and running containerized Cogames.

## Package Contract

At the base of a Coworld package there must be a `coworld_manifest.json` file that adheres to
`coworld_manifest_schema.json`; its inline `game` object declares the Cogame.

The `game` object contains:

- `name`, `version`, and `description`,
- `owner`: the game owner's contact email,
- `runnable`: the game engine runnable with `type`, `image`, optional `run`, and optional public `env`,
- `config_schema`: JSON Schema for the config file supplied to the container,
- `results_schema`: JSON Schema for the results file written by the container,
- `protocols.player`: document object for the player websocket protocol documentation,
- `protocols.global`: document object for the global websocket protocol documentation.

Protocol document objects are explicit: `{ "type": "uri", "value": "https://..." }` links to public HTTP(S) docs, and
`{ "type": "text", "value": "..." }` stores deliberately inline documentation text.

The `config_schema` must require `tokens`, an array of runner-managed player tokens. `tokens` must declare an exact
fixed length with equal `minItems` and `maxItems`; that length is the Cogame's runner-managed player count. Author-owned
game configs such as certification fixtures and Coworld variants must omit `tokens`. The runner injects generated tokens
when it derives the concrete runtime config. The `results_schema` must require `scores`, one scalar score per player
slot, and may define additional game-specific result fields.

## Container Contract

The container referenced by `runnable.image` must implement the runtime contract below.

This contract is platform-owned and hardcoded in the runner and certifier. A game container does not receive a runtime
contract file; it implements this behavior directly.

The runner supplies:

- `COGAME_CONFIG_URI`: URI from which to GET the config JSON file,
- `COGAME_RESULTS_URI`: URI to which to POST the final results,
- `COGAME_SAVE_REPLAY_URI`: URI to which to POST the game's replay artifact.

Games must support `file://` URIs. Hosted runners may provide other writable URI schemes for results and replay when the
game image supports them.

These environment variables put the container in rollout mode. In rollout mode, the game container listens on
`0.0.0.0:8080` and exposes:

- `GET /healthz`
- `GET /clients/player?slot=0&token=...&...`
- `WEBSOCKET /player?slot=0&token=...&...`
- `GET /clients/global` -- serves the global viewer ui, connected to this game, without the need for url args
- `WEBSOCKET /global` -- used by a global viewer, such as the ui above or a native ui, to connect to the game

HTTP `GET /clients/player` must serve a browser client for one player slot. HTTP `GET /clients/global` must serve a
browser client for live episode viewing. The served clients read the complete URL query string before opening their
websocket connection. If the query contains `address`, the client uses that value as the complete websocket URL after
converting `http`/`https` to `ws`/`wss`; it must not merge other page query params into that URL. Otherwise, it derives
the websocket URL from the client page URL by replacing `/clients/player` with `/player` or `/clients/global` with
`/global` and preserving the page query params such as `slot`, `token`, and game-owned params. For example,
`http://<engine-host>/clients/player?slot=0&token=...&role=...` serves the player client, and that client opens
`ws://<engine-host>/player?slot=0&token=...&role=...`. A proxy may instead serve
`https://<proxy>/clients/player?address=wss://<proxy>/player?slot=0&token=...`, which tells the client to connect to
`wss://<proxy>/player?slot=0&token=...`.

Games may implement local development admin controls however they want. By convention, `GET /clients/admin` serves the
browser admin UI and `WEBSOCKET /admin?...` accepts admin commands such as pausing, unpausing, or changing tick rate.
The admin protocol is game-owned and the platform must not expose `/admin` in production.

The `/global` websocket endpoint must accept viewer connections after an episode has already started. A viewer that
connects mid-episode must receive enough state over the global protocol to render from its join point without requiring
the episode to restart.

The `/player` websocket endpoint must allow a player to reconnect to the same slot with the same token while the episode
is still running. The slot's game state survives disconnects. During a disconnect, the game may advance that slot with
no-op actions or another documented disconnected-player behavior until the player reconnects.

To view replays, the runner starts the same Cogame image as a warm replay server and supplies:

- `COGAME_REPLAY_SERVER=1`: the container serves replay viewers and waits for replay URIs on viewer requests.

In replay server mode, the game container listens on `0.0.0.0:8080` and exposes:

- `GET /healthz`
- `GET /clients/replay?uri=<uri>`
- `WEBSOCKET /replay?uri=<uri>`

HTTP `GET /clients/replay?uri=<uri>` must serve a browser replay viewer. The replay viewer opens
`WEBSOCKET /replay?uri=<uri>`; the game server loads that replay artifact and sends replay state plus game-owned control
commands such as start, stop, seek, or speed changes. The replay artifact format and replay websocket protocol are
game-owned.

## Coworld Contract

A Coworld declares exactly one Cogame through the inline `game` object in `coworld_manifest.json`.

Coworld certification resolves the Coworld's fixture into one end-to-end smoke episode for the referenced Cogame.

## Episode Config

The runner receives an episode request that adheres to `runner/episode_request_schema.json`. It has the game config,
player runnables, and output destinations. Per-player game metadata belongs in `game_config`. The game must treat
player-supplied connection metadata as untrusted.

## Episode Lifecycle

1. The runner receives episode config containing `game_config`, `players`, and artifact output URIs.
2. The runner generates a random string token for each player slot.
3. The runner writes game config JSON matching the manifest's `config_schema` to a URI, inserting `tokens` with the
   generated token array.
4. The runner starts the game engine container and supplies:
   - `COGAME_CONFIG_URI`: URI from which to GET the config JSON file,
   - `COGAME_RESULTS_URI`: URI to which to POST the final results,
   - `COGAME_SAVE_REPLAY_URI`: URI to which to POST the game's replay artifact.
5. The runner records all stdout and stderr from the game engine.
6. The container boots, GETs its initial config, and listens for HTTP and websocket traffic on `0.0.0.0:8080`.
7. The game engine exposes `GET /healthz`, which returns `200` when the container is ready to accept connections.
8. For each player, the runner:
   - decides which policy image corresponds to which slot,
   - starts one container per policy runnable,
   - supplies `COGAMES_ENGINE_WS_URL=ws://<engine-host>/player?slot=<slot>&token=<token>` to the policy container.
9. The game rejects player connections whose `token` does not match the token for that slot.
10. Browser player clients may request `GET /clients/player?slot=<slot>&token=<token>&...`; the served client opens the
    `/player` websocket with the same query params, unless an `address` query param supplies the full websocket URL.
11. Browser global clients may request `GET /clients/global`; the served client opens the `/global` websocket with the
    same query params, unless an `address` query param supplies the full websocket URL.
12. Global websocket viewers may connect before or during the episode through `/global`.
13. Players may disconnect and reconnect to the same slot with the same token.
14. The game engine progresses the game after each player connects.
15. When the game ends, it POSTs results to `COGAME_RESULTS_URI` and a replay artifact to `COGAME_SAVE_REPLAY_URI`. The
    results file is JSON matching `results_schema`, and the game engine stops responding to `/healthz` with 200.
16. The runner uploads results, replay, and logs to the episode config output URIs.

## Replay Lifecycle

1. The runner downloads or otherwise materializes a replay artifact produced by the same Cogame.
2. The runner starts or reuses a game engine container with `COGAME_REPLAY_SERVER=1`.
3. A browser requests `GET /clients/replay?uri=<uri>`; the served client opens `WEBSOCKET /replay?uri=<uri>`.
4. Replay playback and controls are implemented by the game-owned replay websocket protocol.
