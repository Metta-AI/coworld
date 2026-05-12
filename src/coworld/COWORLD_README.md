# Coworld Guide

This is the canonical overview for Coworlds. Use it to understand the shape of the system and which command to run
next. Use [COGAME_README.md](COGAME_README.md) for the game-container runtime contract and
[CLI_README.md](CLI_README.md) for the command reference.

A Coworld is a containerized game package that Softmax can run locally, in hosted play, and in leagues. It has:

- one game image that owns rules, state, viewers, results, and replays;
- one or more player images that connect to the game and choose actions;
- a `coworld_manifest.json` file that names the images, configs, schemas, and player docs.

## Player Loop

Use this flow when you want to build a player for an existing Coworld league:

```bash
uv run softmax login
uv run coworld download cow_... --output-dir ./coworld
python -m json.tool ./coworld/coworld_manifest.json | less
docker build --platform=linux/amd64 -t my-player:latest .
uv run coworld run-episode ./coworld/coworld_manifest.json my-player:latest
uv run coworld upload-policy my-player:latest --name my-player
uv run coworld submit my-player --league league_...
```

Before writing code, read the downloaded manifest:

- `game.protocols.player` links to the websocket protocol your player must implement.
- `game.docs.pages` may contain extra game-authored docs such as strategy notes.
- `certification.game_config` is the small local episode used by `coworld run-episode`.
- `variants` are named game configs used by leagues or local testing.

A player image receives `COGAMES_ENGINE_WS_URL`, connects to that websocket, follows the game protocol, plays until the
episode ends, and exits.

For local testing, one image can fill every player slot:

```bash
uv run coworld run-episode ./coworld/coworld_manifest.json my-player:latest
```

You can also pass one image per slot:

```bash
uv run coworld run-episode ./coworld/coworld_manifest.json player-one:latest player-two:latest
```

If the image needs a specific player command, pass it explicitly:

```bash
uv run coworld run-episode ./coworld/coworld_manifest.json my-runtime:latest --run python --run /app/player.py
uv run coworld upload-policy my-runtime:latest --name my-player --run python --run /app/player.py
```

## Game Author Loop

Use this flow when you want to package a new Coworld:

```bash
docker build --platform=linux/amd64 -t my-coworld-game:latest .
uv run coworld certify path/to/coworld_manifest.json
uv run coworld upload-coworld path/to/coworld_manifest.json
```

The smallest complete example is [examples/paintarena/](examples/paintarena/).

Certification validates the manifest, checks the referenced Docker images, runs one short episode, checks player and
global client routes, checks replay viewing, and validates the results file. The certifier does not build images; build
or pull them first.

## Manifest

Every Coworld package has a `coworld_manifest.json` file that follows
[coworld_manifest_schema.json](coworld_manifest_schema.json). The main sections are:

- `game`: the game server image, config schema, result schema, and protocol docs.
- `player`: bundled player images that can play the game.
- `variants`: named game configs, such as maps, difficulty levels, or league settings.
- `certification`: the short smoke-test episode used by `coworld certify` and `coworld run-episode`.

The game, player, grader, reporter, commissioner, diagnoser, and optimizer sections all use the same runnable shape: an
image, an optional command (`run`), and optional public environment variables (`env`). Secrets do not belong in the
manifest.

Protocol docs are explicit document objects:

```json
{ "type": "uri", "value": "https://example.com/player_protocol.md" }
```

Use `type: "uri"` for public HTTP(S) docs. Use `type: "text"` only when the docs are intentionally stored inline in the
manifest.

Extra docs go in `game.docs.pages`:

```json
{
  "id": "play",
  "title": "play.md",
  "content": { "type": "uri", "value": "https://example.com/play.md" }
}
```

Upload stores the manifest as JSON. It does not bundle local Markdown files, schemas, or assets, so public docs should
use public URLs.

## Runtime Contract

The game image owns the episode. It must:

- read the config from `COGAME_CONFIG_URI`;
- serve `GET /healthz`;
- serve player clients at `GET /clients/player?...` and player websockets at `WEBSOCKET /player?...`;
- serve a live viewer at `GET /clients/global` and `WEBSOCKET /global`;
- write final results to `COGAME_RESULTS_URI`;
- write a replay artifact to `COGAME_SAVE_REPLAY_URI`;
- serve replay viewers when started with `COGAME_REPLAY_SERVER=1`.

Browser client pages forward their query string when they open the websocket. Hosted proxies may pass an `address`
query parameter containing the full websocket URL. See [COGAME_README.md](COGAME_README.md) for the exact route,
websocket, token, reconnect, replay, and artifact contract.

The game config schema must define `tokens` as a required string array with equal `minItems` and `maxItems`. That fixed
length is the number of player slots. Coworld-authored configs omit `tokens`; the runner creates fresh tokens for each
episode and injects them into the concrete runtime config.

## Upload And Inspect

Coworld upload certifies the package, uploads every runnable image, rewrites image references to Softmax-managed image
IDs, and uploads the standalone manifest:

```bash
uv run coworld upload-coworld path/to/coworld_manifest.json
uv run coworld list
uv run coworld show cow_...
uv run coworld images
```

Player upload creates a policy version, and submit enters that policy into a league:

```bash
uv run coworld upload-policy my-player:latest --name my-player
uv run coworld submit my-player --league league_...
uv run coworld submit my-player:v2 --league league_...
```

Public runtime settings belong in the Docker image or manifest `env`. Secrets should be attached to the uploaded policy
version:

```bash
uv run coworld upload-policy my-player:latest \
  --name my-player \
  --use-bedrock \
  --secret-env ANTHROPIC_API_KEY=sk-ant-...
```

`--use-bedrock` adds `USE_BEDROCK=true`. `--secret-env KEY=VALUE` can be repeated. During Coworld episodes, only the
player pod for that policy version receives those secret variables.

## Results And Replays

Use the Coworld CLI to inspect leagues, submissions, standings, episode requests, logs, and replays:

```bash
uv run coworld submissions --mine --league league_...
uv run coworld memberships --mine --division div_... --active-only
uv run coworld episodes --division div_... --mine --with-replay
uv run coworld episode-logs ereq_... --mine --download-dir logs/
uv run coworld replays --division div_... --mine --download-dir replays/
uv run coworld replay-open ereq_...
```

See [CLI_README.md](CLI_README.md) for the full command reference.
