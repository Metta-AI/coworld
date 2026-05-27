# Coworld Guide

`coworld` is the public CLI and Python package for Softmax v2 tournaments. Use it to download Coworlds, create starter
policies, run local episodes, host live play sessions for uploaded Coworlds, upload game and policy containers, submit
policies to leagues, and inspect standings, logs, and replays.

A Coworld is the unit Softmax can run locally, in hosted play, and in leagues. At its core, it combines:

- one **game** container that owns rules, state, viewers, results, and replays;
- one or more **player** containers that connect to the game and choose actions;
- a `coworld_manifest.json` file that names the containers, configs, schemas, protocols, and docs.

Every Coworld also declares five **supporting role sections** in its manifest:

- **commissioner**: drives league rounds — schedules episodes, assigns players to slots, collates results, and decides
  promotions/relegations across divisions.
- **reporter**: turns episode artifacts into rendered highlights (Markdown or HTML) and machine-readable event logs.
- **grader**: emits a scalar score for how interesting or useful an episode was from the game creator's perspective.
- **diagnoser**: evaluates a target policy against a Coworld's episode artifacts and emits policy-facing advice.
- **optimizer**: ingests episode artifacts, grades, and diagnoser output to drive local policy iteration.

**All seven role sections are required in every `coworld_manifest.json`:** the single `game` object plus the six
runnable arrays `player`, `commissioner`, `reporter`, `grader`, `diagnoser`, `optimizer`. `player[]` and `reporter[]`
and `grader[]` must contain at least one entry. Coworld authors who do not have a custom reporter or grader may
reference `ghcr.io/metta-ai/reporters-default:latest` and `ghcr.io/metta-ai/graders-default:latest`; the remaining
supporting role arrays may stay empty until their platform contracts require runnable entries. See
[Role Status](#role-status) below for which roles have a live platform contract today.

During a league episode, the platform starts the game container plus one submitted policy container per player slot.
Public users normally build policy containers and submit them to existing Coworld leagues. Game authors build game
containers and publish complete Coworld packages including all seven role sections.

Use [GAME_RUNTIME_README.md](GAME_RUNTIME_README.md) for the game-container runtime contract and
[CLI_README.md](CLI_README.md) for the command reference. Use [API_GUIDE.md](API_GUIDE.md) when a coding agent needs
to call the public Softmax/Coworld API directly.

## Role Status

> **Roles vs runnables.** A _role_ is a function a Coworld needs to fulfill — game, player, commissioner, reporter,
> grader, diagnoser, or optimizer. A _runnable_ is the concrete container (image plus command and env) that fulfills a
> role. The manifest declares one game runnable (at `manifest.game.runnable`) and role-specific runnable arrays (in
> `manifest.player[]`, `manifest.commissioner[]`, and so on). When this guide says "the reporter role" it means the
> function; "a reporter runnable" means a specific container in `manifest.reporter[]`.

Every Coworld role is documented with one of three status labels describing how complete its platform integration is
today. New documents and code in this package must use these labels consistently.

- **live**: the role has a full runtime contract that the platform exercises end to end. The contract is stable enough
  to build against.
- **contract defined, runtime pending**: the role has a written contract (in `docs/roles/<role>.md` and/or a
  `docs/specs/` document) and may have partial or in-process implementations, but the platform does not yet invoke a
  containerized runnable for this role automatically. Manifests must still declare the section; expect the runtime
  integration to land soon.
- **reserved**: the role is declared in the manifest schema and has a purpose statement in `docs/roles/<role>.md`, but
  no input/output contract or platform integration exists yet. The manifest section is still required, but it can stay
  empty until the role has a concrete runnable contract.

| Role         | Status                            |
| ------------ | --------------------------------- |
| game         | live                              |
| player       | live                              |
| commissioner | contract defined, runtime pending |
| reporter     | contract defined, runtime pending |
| grader       | contract defined, runtime pending |
| diagnoser    | reserved                          |
| optimizer    | reserved                          |

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

Coworld manifests must include game-authored docs in `game.docs.pages`: exactly one `rules.md` page for game-specific
rules and exactly one game-specific `play_*.md` guide for player setup. Examples include:

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
- `game.docs.pages` must include exactly one `rules.md` page plus exactly one game-specific `play_*.md` guide, and may
  contain extra game-authored docs such as strategy notes.
- `certification.game_config` is the small local episode used by `coworld run-episode`.
- `variants` are named game configs used by leagues or local testing.

A player image receives `COWORLD_PLAYER_WS_URL`, connects to that websocket, follows the game protocol, plays until the
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

For exact local reproduction, pass the same runner request shape used by hosted Coworld jobs:

```bash
uv run coworld run-episode ./coworld/<coworld-id>/coworld_manifest.json episode_request.json
uv run coworld play ./coworld/<coworld-id>/coworld_manifest.json episode_request.json
```

`episode_request.json` follows [runner/episode_request_schema.json](runner/episode_request_schema.json). It supplies the
game config, per-slot player images, commands, environment variables, episode tags, and optional policy names. The
manifest argument remains the authoritative Coworld package and must match the manifest embedded in the request.

`run-episode` waits for the local episode and writes results, the game-written replay artifact, and logs. `play` uses
the same episode request/default fixture, writes the same artifact shape, prints the local player/global/admin browser
links, and opens the global link unless `--no-open-browser` is passed. Both commands accept `--output-dir` for artifact
placement. Without an explicit request file, both commands use the manifest's `certification` fixture;
`play --variant <variant-id>` can launch a named variant for interactive inspection.

## Hosted Play Sessions

Hosted play is the shared browser-play path for uploaded Coworlds:

```bash
uv run coworld hosted-game create <coworld-id>
uv run coworld hosted-game create <coworld-id> --variant <variant-id>
uv run coworld hosted-game join <play-session-id>
```

`hosted-game create` starts the Coworld game container in Kubernetes and prints a player command, a player URL, and a
spectator URL when spectators are enabled. `hosted-game join` claims one browser player slot for the authenticated user;
joining the same session again returns the same slot.

Hosted play sessions are live lobbies, not league matches. They do not launch submitted policy containers and do not
record Observatory episode artifacts. Use local `play`/`run-episode` for policy-container debugging and leagues for
hosted policy evaluation, standings, episode logs, and replays.

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

Publishing a Coworld is separate from submitting a policy. `upload-coworld` uploads the game package and every bundled
role implementation it references — the `game.runnable` container plus each entry in `player[]`, `commissioner[]`,
`reporter[]`, `grader[]`, `diagnoser[]`, and `optimizer[]`. `upload-policy` uploads a player's policy container and
creates a policy version for league submission.

## Manifest

Every Coworld package has a `coworld_manifest.json` file. The main sections are:

- `game`: game container and its protocols, config schema, results schema, and game-authored docs.
- `player`: bundled player images that can play the game. Must contain at least one entry.
- `reporter`: bundled reporter runnables. Must contain at least one entry; Coworlds without a custom reporter may
  reference `ghcr.io/metta-ai/reporters-default:latest`.
- `grader`: bundled grader runnables. Must contain at least one entry; Coworlds without a custom grader may reference
  `ghcr.io/metta-ai/graders-default:latest`.
- `commissioner`, `diagnoser`, `optimizer`: arrays of bundled supporting runnables. The sections are required and may be
  empty until their contracts require runnable entries.
- `variants`: named game configs, such as maps, difficulty levels, or league settings.
- `certification`: the short smoke-test episode used by `coworld certify` and `coworld run-episode`.

For the field-by-field reference — runnable shape, the `type` field, the `game` sub-object, variant fields,
certification fields, document objects, and `game.docs.pages` requirements — see
[MANIFEST_README.md](MANIFEST_README.md). Role-specific contracts live under `docs/roles/`: [game](docs/roles/game.md),
[player](docs/roles/player.md), [commissioner](docs/roles/commissioner.md), [reporter](docs/roles/reporter.md),
[grader](docs/roles/grader.md), [diagnoser](docs/roles/diagnoser.md), and [optimizer](docs/roles/optimizer.md);
[docs/roles/OVERVIEW.md](docs/roles/OVERVIEW.md) covers how the roles compose.

The manifest schema is generated at [coworld_manifest_schema.json](coworld_manifest_schema.json). Upload stores the
manifest as JSON; it does not bundle local Markdown files, schemas, or other assets, so referenced URIs should be
public.

Manifests live at the Coworld level only. Individual runnables do not carry their own Coworld manifest — each is just an
`image` reference with optional `run` and `env`. A few unrelated documents elsewhere in the system are also named
`manifest.json` but are not Coworld manifests: a reporter's output `.zip` contains an internal `manifest.json` that
flags its render target and event log (see [`docs/roles/reporter.md`](docs/roles/reporter.md)); an episode bundle
contains an internal `manifest.json` describing the files inside it (see
[`EPISODE_BUNDLE_README.md`](EPISODE_BUNDLE_README.md)); and per-role-repo implementations carry a `CATALOG.yaml` for
discoverability (see [`docs/specs/0045-coworld-role-repos.md`](../../../../docs/specs/0045-coworld-role-repos.md)). None
of those are Coworld manifests.

## Role Artifact Flow

The role `type` on each runnable is the manifest-level contract selector. The current Coworld artifact flow is:

```text
episode config -> (game <-one-to-many-> players) -> replay and results
replay and results -> reporter -> HTML, commentary, parquet stats, or other experience reports
replay and results -> grader -> scalar creator-interest score
policy, coworld manifest, and optional experience reports -> diagnoser -> policy advice
coworld manifest, many experience reports, grades, and optional diagnoser output -> optimizer
```

Reporters compress sparse episode experience into dense highlight signals: narrative color, news-caster summaries,
interesting moments, structured stats, or machine-usable parquet dumps. They read a single `COGAME_EPISODE_BUNDLE_URI`
(a `.zip` containing the episode's artifacts), write a single `.zip` to `COGAME_REPORT_URI`, and flag their renderable
and event-log outputs via a top-level `manifest.json` inside the output zip. A stats-parquet reporter declares its
parquet via the `event_log` field and uses the shared `(ts: int64, player: int64, key: string, value: string)` schema,
where `player` is the player slot or `-1` for global facts. See [`docs/roles/reporter.md`](docs/roles/reporter.md) for
the full contract. Reporter execution is orchestration-owned: a local CLI, hosted button, or automatic Column pipeline
can decide when to run a reporter and which prior reporter outputs to pass through.

Graders consume replay/results artifacts and emit a scalar score for how interesting or useful the episode was from the
game creator's perspective. A grader is intentionally smaller than a reporter: it produces a ranking signal, not a full
human-readable report.

Diagnosers consume a target policy, plus optional Coworld manifest and experience reports, and emit policy-facing assay
results or advice. They are the canonical Coworld home for a battery of policy tests such as "your policy does X with Y
skill" across many X/Y checks. This is the contract boundary with reporters: reporters explain experience; diagnosers
evaluate a policy using that experience and any additional local assays.

Optimizers are game-agnostic improvement apps. They target a Coworld plus optional policy workspace, ingest any useful
experience reports, diagnoser output, and game/protocol docs, and drive local policy iteration.

## Runtime Contract

The game image owns the episode. It must:

- read the config from `COGAME_CONFIG_URI`;
- bind to `COGAME_HOST` and `COGAME_PORT`, defaulting to `0.0.0.0:8080` when omitted;
- serve `GET /healthz`;
- serve player clients at `GET /client/player?...` and player websockets at `WEBSOCKET /player?...`;
- serve a live viewer at `GET /client/global` and `WEBSOCKET /global`;
- write final results to `COGAME_RESULTS_URI`;
- write a replay artifact to `COGAME_SAVE_REPLAY_URI`;
- serve replay clients at `GET /client/replay?uri=<uri>` and replay websockets at `WEBSOCKET /replay?uri=<uri>` when
  started with `COGAME_REPLAY_SERVER=1`.

Browser client pages forward their page query string into the websocket they open. When the game is served through a
hosted proxy that strips websocket query strings, the platform passes an `address` query parameter on the page URL
containing the full websocket URL to use instead. See
[GAME_RUNTIME_README.md § Browser Clients](GAME_RUNTIME_README.md#browser-clients) for the full contract, including the
replay URI flow.

Coworld replays have one hosted entrypoint across games: the platform iframes the game-owned `/client/replay?uri=<uri>`
page, and the page opens game-owned replay HTTP or WebSocket routes on the same runtime. Those replay routes must keep
the replay artifact URI in the query string so proxies can preserve it end to end.

The game config schema must define `tokens` as a required string array with equal `minItems` and `maxItems`. That fixed
length is the number of player slots. Coworld-authored configs omit `tokens`; the runner creates fresh tokens for each
episode and injects them into the concrete runtime config.

The runner uploads each episode artifact to a separate URI; it does not produce a single bundled output. When a consumer
(reporter, grader, diagnoser, optimizer, or any CLI command that needs a full-episode view) wants those artifacts as a
unit, it requests an **episode bundle** — a zip assembled on demand from the per-URI artifacts. See
[EPISODE_BUNDLE_README.md](EPISODE_BUNDLE_README.md) for the bundle contract, the `COGAME_EPISODE_BUNDLE_URI` env var
that supporting runnables read, and the CLI/library/API surfaces for requesting a bundle.

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

### Bedrock and LLM credentials

Coworld tournaments run on AWS. When a policy opts into `--use-bedrock`, the hosted runner gives the player pod an IAM
role with Bedrock permissions — no API key needed. Softmax covers the Bedrock token usage, so players using Bedrock do
not need to bring their own LLM credentials or pay for inference.

For other LLM providers (Anthropic API, OpenAI, etc.), use `--secret-env` to attach your own API keys. Those keys are
stored in AWS Secrets Manager and injected at runtime, but you manage and fund them yourself.

For local testing, `coworld play` and `coworld run-episode` both support `--use-bedrock` and `--secret-env`, matching
the hosted environment:

```bash
uv run coworld play ./coworld/<coworld-id>/coworld_manifest.json my-player:latest \
  --use-bedrock \
  --secret-env ANTHROPIC_API_KEY=sk-ant-...

uv run coworld run-episode ./coworld/<coworld-id>/coworld_manifest.json my-player:latest \
  --secret-env OPENAI_API_KEY=sk-...
```

## Results And Replays

Use the Coworld CLI to inspect leagues, submissions, standings, episode requests, logs, and replays:

```bash
uv run coworld submissions --mine --league league_...
uv run coworld memberships --mine --division div_... --active-only
uv run coworld rounds --division div_... --status completed
uv run coworld episodes --round round_... --mine --with-replay
uv run coworld episode-logs ereq_... --mine --download-dir logs/
uv run coworld replays --round round_... --mine --download-dir replays/
uv run coworld replay-open ereq_...
```

`episode-logs --mine` downloads accessible per-player logs. Use `episode-logs --game` for episodes with a game log
artifact.

See [CLI_README.md](CLI_README.md) for the full command reference.
