# Coworld Guide

`coworld` is the public CLI and Python package for Softmax v2 tournaments. Use it to download Coworlds, create starter
policies, run local episodes, upload game and policy containers, submit policies to leagues, and inspect standings,
logs, and replays.

A Coworld is the unit Softmax can run locally, in hosted play, and in leagues. It combines:

- one game container that owns rules, state, viewers, results, and replays;
- one or more player or policy containers that connect to the game and choose actions;
- a `coworld_manifest.json` file that names the containers, configs, schemas, protocols, and docs.

During a league episode, the platform starts the game container plus one submitted policy container per player slot.
Public users normally build policy containers and submit them to existing Coworld leagues. Game authors build game
containers and publish complete Coworld packages.

Use [GAME_RUNTIME_README.md](GAME_RUNTIME_README.md) for the game-container runtime contract and
[CLI_README.md](CLI_README.md) for the command reference.

## Install

In a project:

```bash
uv init --bare --name my-coworld-player
uv add "coworld[auth]"
```

Commands that talk to Observatory use `softmax-cli` auth, included in the `auth` extra:

```bash
uv run softmax login
uv run coworld leagues
```

For one-off CLI use outside a project:

```bash
uv tool install "coworld[auth]"
```

## Quickstart: Play A Public League

Pick a league, download its Coworld, read the manifest and linked game docs, test locally, upload a policy image, and
submit it to the league:

```bash
uv run softmax login
uv run coworld leagues
uv run coworld download <coworld-name-or-id> --output-dir ./coworld
python -m json.tool ./coworld/<coworld-id>/coworld_manifest.json | less
docker build --platform=linux/amd64 -t my-player:latest .
uv run coworld run-episode ./coworld/<coworld-id>/coworld_manifest.json my-player:latest
uv run coworld upload-policy my-player:latest --name my-player
uv run coworld submit my-player --league league_...
```

`coworld download` stores each remote Coworld under `./coworld/<coworld-id>/`. Use `coworld play cow_...` for local
interactive play; it reuses `./coworld/<coworld-id>/coworld_manifest.json` when that cached manifest exists and
downloads the Coworld into that cache when it does not.

Use the CLI to inspect the tournament:

```bash
uv run coworld leagues
uv run coworld submissions --mine --league league_...
uv run coworld results league_...
uv run coworld rounds --league league_...
uv run coworld replays --league league_... --mine --download-dir replays/
```

Coworld manifests must include game-authored docs in `game.docs.pages`: `rules.md` for game-specific rules and a
game-specific `play_*.md` guide for player setup. Examples include:

| Coworld       | Download name   | Guide                                     |
| ------------- | --------------- | ----------------------------------------- |
| Among Them    | `among_them`    | <https://softmax.com/play_amongthem.md>   |
| Cogs vs Clips | `cogs_vs_clips` | <https://softmax.com/play_cogsvsclips.md> |

## Player Loop

Use this flow when you want to build a player for an existing Coworld league:

```bash
uv run softmax login
uv run coworld download <coworld-name-or-id> --output-dir ./coworld
python -m json.tool ./coworld/<coworld-id>/coworld_manifest.json | less
docker build --platform=linux/amd64 -t my-player:latest .
uv run coworld run-episode ./coworld/<coworld-id>/coworld_manifest.json my-player:latest
uv run coworld upload-policy my-player:latest --name my-player
uv run coworld submit my-player --league league_...
```

Before writing code, read the downloaded manifest:

- `game.protocols.player` links to the websocket protocol your player must implement.
- `game.docs.pages` may include `rules.md` plus a game-specific `play_*.md` guide, and may contain extra game-authored
  docs such as strategy notes.
- `certification.game_config` is the small local episode used by `coworld run-episode`.
- `variants` are named game configs used by leagues or local testing.

A player image receives `COGAMES_ENGINE_WS_URL`, connects to that websocket, follows the game protocol, plays until the
episode ends, and exits.

For local `coworld run-episode` and `coworld play`, printed browser/debug links stay on `127.0.0.1:<port>`. Dockerized
player containers use Docker's private `coworld-local` network and connect to the game through
`ws://coworld-game-<run-id>:8080/...`, so stock Linux Docker Engine users should not need UFW or `docker0` firewall
changes. Hosted tournament episodes use Kubernetes Service DNS instead.

Starter policy templates are available for games that ship one:

```bash
uv run coworld make-policy <starter-policy-name> -o my-player
```

Use `uv run coworld make-policy --help` to list packaged templates. The copied starter policy directory is a starting
point for game logic and may include a Dockerfile. Build it, run a local episode, then upload the resulting image with
`coworld upload-policy`.

For local testing, one image can fill every player slot:

```bash
uv run coworld run-episode ./coworld/<coworld-id>/coworld_manifest.json my-player:latest
```

You can also pass one image per slot:

```bash
uv run coworld run-episode ./coworld/<coworld-id>/coworld_manifest.json player-one:latest player-two:latest
```

If the image needs a specific player command, pass it explicitly:

```bash
uv run coworld run-episode ./coworld/<coworld-id>/coworld_manifest.json my-runtime:latest --run python --run /app/player.py
uv run coworld upload-policy my-runtime:latest --name my-player --run python --run /app/player.py
```

## Game Author Loop

Use this flow when you want to package a new Coworld:

```bash
uv run coworld build path/to/compose.yaml path/to/coworld_manifest_template.json 0.1.0 build/coworld_manifest.json
uv run coworld certify build/coworld_manifest.json
uv run coworld upload-coworld build/coworld_manifest.json
```

The smallest complete example is [examples/paintarena/](examples/paintarena/).

`coworld build` runs the Compose build, copies the manifest template to a hydrated manifest, writes the requested
`game.version`, and replaces build image tags with content-derived local tags. Keep `coworld_manifest_template.json`
checked in without a version; use the hydrated `coworld_manifest.json` for certify, play, run, and upload.

Certification validates the manifest, checks the referenced Docker images, runs one short episode, checks player and
global client routes, checks replay viewing, and validates the results file.

Publishing a Coworld is separate from submitting a policy. `upload-coworld` uploads the game package and bundled player
images. `upload-policy` uploads a player's policy container and creates a policy version for league submission.

## Manifest

Every Coworld package has a `coworld_manifest.json` file that follows
[coworld_manifest_schema.json](coworld_manifest_schema.json). The main sections are:

- `game`: the game server image, config schema, result schema, protocol docs, and game-authored docs.
- `player`: bundled player images that can play the game. This section is required.
- `commissioner`, `reporter`, `grader`, `diagnoser`, and `optimizer`: optional role runnable sections. Declare the
  section as an empty array when the Coworld supports the role in its manifest contract but has no bundled runnable yet.
- `variants`: named game configs, such as maps, difficulty levels, or league settings.
- `certification`: the short smoke-test episode used by `coworld certify` and `coworld run-episode`.

The game and role sections all use the same runnable shape: an
image, an optional command (`run`), and optional public environment variables (`env`). Secrets do not belong in the
manifest.

Protocol docs are explicit document objects:

```json
{ "type": "uri", "value": "https://example.com/player_protocol.md" }
```

Use `type: "uri"` for public HTTP(S) docs. Use `type: "text"` only when the docs are intentionally stored inline in the
manifest.

Game docs go in `game.docs.pages`. Coworld manifests must include `rules.md` with game-specific rules and a
game-specific `play_*.md` guide that player-facing league pages can surface directly:

```json
[
  {
    "id": "rules.md",
    "title": "rules.md",
    "content": { "type": "uri", "value": "https://example.com/rules.md" }
  },
  {
    "id": "play_myworld.md",
    "title": "play_myworld.md",
    "content": { "type": "uri", "value": "https://example.com/play_myworld.md" }
  }
]
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
- serve replay clients at `GET /clients/replay?uri=<uri>` and replay websockets at
  `WEBSOCKET /replay?uri=<uri>` when started with `COGAME_REPLAY_SERVER=1`.

Browser client pages forward their query string when they open the websocket. Hosted proxies may pass an `address` query
parameter containing the full websocket URL. See [GAME_RUNTIME_README.md](GAME_RUNTIME_README.md) for the exact route,
websocket, token, reconnect, replay, and artifact contract.

Coworld replays have one hosted entrypoint across games: the platform iframes the game-owned
`/clients/replay?uri=<uri>` page, and the page opens game-owned replay HTTP or WebSocket routes on the same runtime.
Those replay routes must keep the replay artifact URI in the query string so proxies can preserve it end to end.

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
