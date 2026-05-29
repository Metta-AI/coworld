# Game Role

**Status:** live

## What it does

The game role owns the episode. The game runnable receives a concrete game config, accepts one or more player
connections, advances the world, and writes the results and replay artifacts that later tools consume. Every Coworld
manifest has exactly one game runnable.

The game is the only role with a live HTTP/WebSocket server contract. Player runnables connect to it during the
episode; supporting roles consume its completed artifacts later.

## Where it lives in the manifest

`manifest.game.runnable`, with `type: "game"`. The game is the only role whose runnable is a single object rather than
an array. Identifying metadata (`game.name`, `game.version`, `game.description`, `game.owner`) lives one level up on
`manifest.game` itself.

See [`COWORLD_MANIFEST.md`](../COWORLD_MANIFEST.md) for the manifest semantics and generated-schema source of truth.

The `game` object also requires `game.docs.pages` to include exactly one `rules.md` entry and exactly one `play_*.md`
entry for player onboarding. Those manifest docs are public HTTP(S) or inline references surfaced after upload.

## Contract

The game runnable is a long-running container that listens on `COGAME_HOST:COGAME_PORT`, defaulting to `0.0.0.0:8080`.
It must:

- Read its concrete game config from `COGAME_CONFIG_URI` at startup.
- Serve `GET /healthz` with 200 once it is ready.
- Serve player HTML clients at `GET /client/player?slot=...&token=...`.
- Serve player WebSocket connections at `/player?slot=...&token=...`.
- Serve a live global viewer at `GET /client/global` and `/global`.
- In replay mode, with `COGAME_LOAD_REPLAY_URI` set, serve `GET /client/replay` and `/replay`.
- Write a JSON results artifact to `COGAME_RESULTS_URI` when the episode completes.
- Write replay bytes to `COGAME_SAVE_REPLAY_URI`.

The runner validates the final results against `manifest.game.results_schema`. Replay bytes are game-defined, but the
same game image must be able to load them in replay mode.

## Player slots

`game.config_schema` must require a fixed-length string-array `tokens` field. That fixed length defines the number of
player slots for variants, certification, local play, and hosted runs.

Coworld-authored configs are token-free:

- `variants[].game_config`
- `certification.game_config`

The runner injects fresh tokens into the concrete per-episode config, then starts one player runnable per slot with a
fully formed `COWORLD_PLAYER_WS_URL`.

## Browser clients

The game owns browser-client behavior. Player-facing flows expect `GET /client/player?slot=...&token=...` to serve the
slot-specific player UI. Viewer flows expect `GET /client/global` for live viewing and `GET /client/replay` for replay
mode.

The example Paint Arena protocol docs link here because the exact in-game messages are game-specific, while the route
families and token semantics are Coworld-wide.

## Hosted runtime resources

Hosted tournament runs schedule the game as the parent pod and player runnables as child pods. The current hosted
baseline is 2 CPU and 2Gi memory requests for the game container, runner worker, replay container, and each player
container; see [`KUBERNETES_RUNNER_README.md`](../../runner/KUBERNETES_RUNNER_README.md#hosted-resource-baseline). These
are scheduling requests, not CPU or memory limits.

## Logging

Game stdout and stderr may be exposed to anyone with episode access through the [game logs](../artifacts/GAME_LOGS.md)
artifact and episode bundles. Treat those streams as public diagnostic output.

The game should put authoritative episode state in structured artifacts:

- [`RESULTS.md`](../artifacts/RESULTS.md) for final game-defined results.
- [`REPLAY.md`](../artifacts/REPLAY.md) for replay bytes.
- [`GAME_LOGS.md`](../artifacts/GAME_LOGS.md) for diagnostic logs.

## How it fits with other roles

The game produces the per-episode results, replay, and game-log artifacts. Players interact with the game in-flight
through `/player`; reporters, graders, diagnosers, and optimizers consume completed artifacts after the episode. See
[`README.md`](../README.md) for the full role and artifact flow.

## See Also

- [`PLAYER.md`](PLAYER.md) - player-side runtime contract for the `/player` WebSocket route.
- [`COWORLD_MANIFEST.md`](../COWORLD_MANIFEST.md) - manifest guide and generated-schema pointer.
- [`LIFECYCLE.md`](../LIFECYCLE.md) - local and hosted episode lifecycle.
- [`artifacts/RESULTS.md`](../artifacts/RESULTS.md) - validated results artifact.
- [`artifacts/REPLAY.md`](../artifacts/REPLAY.md) - replay artifact.
- [`artifacts/GAME_LOGS.md`](../artifacts/GAME_LOGS.md) - diagnostic game logs.
- [`README.md`](../README.md) - role status framework, runnable conventions, and artifact flow.
