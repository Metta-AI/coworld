# Game Role

**Status:** live

## What it does

The game role owns the episode. The game runnable receives an episode config, accepts one or more player
connections, advances the world, and emits the replay and results artifacts that supporting runnables consume after
the episode. Every Coworld manifest has exactly one game runnable.

## Where it lives in the manifest

`manifest.game.runnable`, with `type: "game"`. The game is the only role whose runnable is a single object rather
than an array; identifying metadata (`game.name`, `game.version`, `game.description`, `game.owner`) lives one level
up on `manifest.game` itself. See [`MANIFEST_README.md` § `game` Section](../../MANIFEST_README.md#game-section).

## Contract

The game runnable is a long-running container that listens on `0.0.0.0:8080` and follows the runtime contract
documented in [`GAME_RUNTIME_README.md`](../../GAME_RUNTIME_README.md):

- Reads its concrete game config from `COGAME_CONFIG_URI` at startup.
- Serves `GET /healthz` (200 when ready).
- Serves player HTML clients at `GET /clients/player?slot=…&token=…` and player websockets at
  `/player?slot=…&token=…`.
- Serves a live global viewer at `GET /clients/global` and `/global`.
- In replay mode (`COGAME_REPLAY_SERVER=1`), serves `GET /clients/replay?uri=…` and `/replay?uri=…`.
- Writes a validated results file to `COGAME_RESULTS_URI` when the episode completes.
- Writes a replay artifact to `COGAME_SAVE_REPLAY_URI`.

The game is the only role with a runtime websocket-server contract. All supporting runnables run as process-style
containers that consume artifacts after the fact.

Game container stdout and stderr are surfaced to anyone with episode access via the bundling layer's `game_logs`
include token; treat those streams as public. See
[`GAME_RUNTIME_README.md` § Log visibility](../../GAME_RUNTIME_README.md#log-visibility).

## How it fits with other roles

The game runnable produces the per-URI episode artifacts (results, replay, game logs) that the bundling layer
assembles into episode bundles on demand. Supporting runnables — reporter, grader, diagnoser, optimizer — consume
those bundles after the episode. Player runnables connect to the game's websockets during the episode and are the
only role that interacts with the game in-flight. See [`OVERVIEW.md`](OVERVIEW.md) for the full artifact flow.

## See Also

- [`GAME_RUNTIME_README.md`](../../GAME_RUNTIME_README.md) — full runtime contract (URL families, browser-client
  behavior, episode lifecycle, certification, hosted resource baseline).
- [`MANIFEST_README.md`](../../MANIFEST_README.md) — manifest field reference for `manifest.game`.
- [`EPISODE_BUNDLE_README.md`](../../EPISODE_BUNDLE_README.md) — how the game's per-URI outputs flow into bundles
  consumed by supporting runnables.
- [`player.md`](player.md) — the role that connects to the game runnable's websockets in-flight.
- [`OVERVIEW.md`](OVERVIEW.md) — full artifact flow.
