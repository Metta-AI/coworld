# Game Role

**Status:** live

## What it does

The game role owns the episode. The game runnable receives a concrete game config, accepts one or more player
connections, advances the world, and writes the results and replay artifacts that later tools consume. Every Coworld
manifest has exactly one game runnable.

The game is the only role with a live HTTP/WebSocket server contract. Player runnables connect to it during the episode;
supporting roles consume its completed artifacts later.

## Where it lives in the manifest

`manifest.game.runnable`, with `type: "game"`. The game is the only role whose runnable is a single object rather than
an array. Identifying metadata (`game.name`, `game.version`, `game.description`, `game.owner`) lives one level up on
`manifest.game` itself.

See [`COWORLD_MANIFEST.md`](../COWORLD_MANIFEST.md) for the manifest semantics and generated-schema source of truth.

The `game` object also requires `game.docs.readme`, the Coworld's public `README.md` reference for player onboarding,
rules, strategy, setup, and context. Additional `game.docs.pages` entries are optional docs surfaced after upload.
Game-authored pages should stay game-specific; Softmax `play_*.md` pages, when present, own platform setup, upload, and
league-submission steps.

## Contract

The game runnable is a long-running container that listens on `COGAME_HOST:COGAME_PORT`, defaulting to `0.0.0.0:8080`.
It must:

- Read its concrete game config from `COGAME_CONFIG_URI` at startup.
- Serve `GET /healthz` with 200 once it is ready.
- Serve player HTML clients at `GET /client/player?slot=...&token=...`.
- Serve player WebSocket connections at `/player?slot=...&token=...`.
- Serve a live global viewer at `GET /client/global` and `/global`.
- In replay mode, with `COGAME_LOAD_REPLAY_URI` set, serve `GET /client/replay` and `/replay`.
- Make `GET /client/replay` start playback automatically and loop from the recorded end back to tick 0 by default.
- Write a JSON results artifact to `COGAME_RESULTS_URI` when the episode completes.
- Write replay bytes to `COGAME_SAVE_REPLAY_URI`.

The runner validates the final results against `manifest.game.results_schema`. Replay bytes are game-defined, but the
same game image must be able to load them in replay mode.

## Player slots

`game.config_schema` must require a string-array `tokens` field. Tokens are runner-injected player auth values, not a
player-count declaration, so `minItems` and `maxItems` are validity bounds for possible rosters, not the scheduler's
chosen count. The runner injects the concrete tokens after the episode roster is known.

Coworld-authored configs are token-free:

- `variants[].game_config`
- `certification.game_config`

The runner starts one player runnable per scheduled roster slot with a fully formed `COWORLD_PLAYER_WS_URL`.

If the game shows policy or player display names in its UI, replay, results, or logs, it should declare a `players`
array in `game.config_schema`. Each `players[]` item has a required string `name`. Hosted dispatch overwrites
`game_config.players[].name` with resolved names for declared schemas. Local raw configs may set `players[].name`
directly. The same `players` array is also the concrete seat-count source for variable-size games.

Coworld-wide display names use `game_config.players[].name`; game-specific per-slot mechanics remain in the game's own
config fields.

## Browser clients

The game owns browser-client behavior. Player-facing flows expect `GET /client/player?slot=...&token=...` to serve the
slot-specific player UI. Viewer flows expect `GET /client/global` for live viewing and `GET /client/replay` for replay
mode. Replay viewers may expose pause, seek, speed, and loop controls, but the default browser replay surface should
begin playing and wrap back to tick 0 when it reaches the recorded end.

`coworld certify` validates replay liveness for game authors: after the certification episode writes replay bytes, it
starts the same game image in replay mode with `COGAME_LOAD_REPLAY_URI`, verifies `GET /client/replay`, and waits for a
message from `/replay`. Authors should still open the printed replay command and inspect the browser replay before
uploading, because only the game author can confirm that the viewer shows the right game state and controls.

The example Paint Arena protocol docs link here because the exact in-game messages are game-specific, while the route
families and token semantics are Coworld-wide.

## Hosted runtime resources

Hosted tournament runs schedule the game as the parent pod and player runnables as child pods. The current hosted
baseline is 1 CPU / 512Mi for the game container, 250m CPU / 256Mi for the runner worker, 250m CPU / 256Mi for each
player container, and 2 CPU / 2Gi for replay containers; see
[`KUBERNETES_RUNNER_README.md`](../../runner/KUBERNETES_RUNNER_README.md#hosted-resource-baseline). These are scheduling
requests, not CPU or memory limits. Hosted episode Jobs have a 20 minute active deadline.

## Bedrock and AWS access

In hosted runs your game image can call AWS Bedrock by default — Softmax provides Bedrock credentials and region to the
game container at runtime, so you do not need to bake AWS keys into the image or have players opt in. The game container
sees `USE_BEDROCK=true`, `AWS_REGION`, and `AWS_DEFAULT_REGION` set for you; point any Bedrock client (for example
`anthropic.AnthropicBedrock()`) at the default credential chain and it will work. The replay container gets the same
defaults. To override the region or disable the default, set the relevant variables in `manifest.game.runnable.env`.

This is hosted-runtime only. Local `coworld play` / `coworld run-episode` do not provide AWS credentials; for local
Bedrock testing pass host credentials with `--use-bedrock` (see
[`PLAYER.md`](PLAYER.md#secrets-bedrock-and-llm-credentials)). For non-Bedrock LLM providers, supply the provider key
through the player upload path rather than the game image, and keep provider selection in environment variables your
game code reads.

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
