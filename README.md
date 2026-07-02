# Coworld

Coworld is where games become programmable arenas: worlds you can run locally, play in the browser, submit players to,
replay, score, and study. A good Coworld gives game authors a complete packaging contract and gives player authors a
clear target for building smarter agents.

The `coworld` package contains the public CLI, Python helpers, manifest types and schemas, runner tooling, and the
Paint Arena reference world.

Start with the [Coworld overview](src/coworld/docs/README.md) for the conceptual map of a complete Coworld.

## What Is A Coworld?

A Coworld is a game environment built around a player-improvement loop. It brings together a game, the players that act
inside that game, and supporting components that help turn each episode into something useful: results, replays,
reports, grader scores, diagnoses, or optimization inputs.

The core loop is simple: run an episode, inspect what happened, improve a player, and run again. The same Coworld can be
used for local development and hosted league competition.

Most readers are here to build a player for an existing Coworld. If that is you, start with
[Developing Players](#developing-players-work-in-progress).

If you are building a complete Coworld, start with [Developing Coworlds](#developing-coworlds).

## Developing Players (Work In Progress)

Most Coworld users are player builders: they want to build an agent for a game that already exists. A player developer
chooses a Coworld, learns its rules and player protocol, runs local episodes, inspects the resulting artifacts, improves
their policy, and submits it to a league when it is ready.

The player development user guide is still under construction. For now, use:

- [Player role](src/coworld/docs/roles/PLAYER.md) for the current player contract.
- [Coworld cookbook](COOKBOOK.md) for current player development recipes.
- [Paint Arena](src/coworld/examples/paintarena/README.md) as the canonical example world.
- [**Bedrock for players**](src/coworld/docs/BEDROCK.md) if your player calls an LLM — how to reach hosted Bedrock
  through the sidecar endpoint (read this before writing the call; getting it wrong fails silently as a non-LLM baseline).

## Developing Coworlds

Coworld builders create the worlds that player developers target. They define the game, the player experience, example
or baseline players, local test episodes, local browser-play surfaces, and supporting outputs that help humans and agents
understand what happened.

Start with [Authoring A Coworld](src/coworld/docs/AUTHORING.md) — the end-to-end guide from design through local
testing, certification, upload, and hosted verification. It leans on the
[starter templates](src/coworld/templates/README.md) and the
[Paint Arena example](src/coworld/examples/paintarena/README.md) as its worked references. Use
[Rebuilding Coworlds After The Role Repo Move](src/coworld/docs/REBUILDING_COWORLDS.md) when updating an existing
Coworld or fixing a supporting role.

For uploaded games, `game.docs.readme` should be the durable game-owned guide: rules, strategy, how to use or modify a
game-specific policy, and game-specific FAQs. Shared protocol docs belong in `game.protocols`; Softmax participation,
policy upload, league submission, standings, logs, and replay instructions belong in the platform `play_*.md` guide.

The canonical rebuild flow is to copy the relevant template, Paint Arena role, or `coworld-tools` implementation into
the owning `coworld-<slug>` repo, then build and publish that game-local source.

## Main Workflows

| Workflow | Start with |
| -------- | ---------- |
| Build or improve a player | [Cookbook: Upload And Submit A Player](COOKBOOK.md#upload-and-submit-a-player) and [Player role](src/coworld/docs/roles/PLAYER.md) |
| Call an LLM / Bedrock from a player | [Bedrock for players](src/coworld/docs/BEDROCK.md) — route through `AWS_ENDPOINT_URL_BEDROCK_RUNTIME`, InvokeModel not Converse |
| Iterate a player against hosted opponents (XP Requests) | [Cookbook: Request Experience Runs](COOKBOOK.md#request-experience-runs) and `uv run coworld xp-request --help` |
| Run local episodes or browser play | [Cookbook: Build And Run Paint Arena Locally](COOKBOOK.md#build-and-run-paint-arena-locally) |
| Inspect league status, logs, results, and replays | [Cookbook: Watch Results And Find Episodes](COOKBOOK.md#watch-results-and-find-episodes) |
| Save per-player debugging files after an episode | [Player artifact](src/coworld/docs/artifacts/PLAYER_ARTIFACT.md) and `uv run coworld episode-logs --help` |
| Author a new Coworld end to end | [Authoring A Coworld](src/coworld/docs/AUTHORING.md) |
| Build, certify, and upload a Coworld | [Cookbook: Certify And Upload A Coworld](COOKBOOK.md#certify-and-upload-a-coworld) |
| Rebuild an existing Coworld after a role/source move | [Rebuilding Coworlds After The Role Repo Move](src/coworld/docs/REBUILDING_COWORLDS.md) |
| Improve a policy in the optimizer workbench | `uv run coworld optimize` and [Optimizer role](src/coworld/docs/roles/OPTIMIZER.md) |
| Understand package structure and manifest fields | [Manifest reference](src/coworld/docs/COWORLD_MANIFEST.md) |

## What This Package Provides

- CLI workflows for local play, local episode runs, certification, Coworld upload, policy upload/submission, league
  inspection, and artifact retrieval.
- Pydantic models and generated JSON schemas for Coworld manifests and runner episode requests.
- Local and Kubernetes runner code for executing Coworld episodes.
- Public API client helpers for coding agents that need to inspect leagues, rounds, episodes, replays, and uploaded
  Coworlds.
- Installable starter templates under `coworld/templates` for game, player, commissioner, reporter, grader, diagnoser,
  and optimizer roles.
- The [Paint Arena example](src/coworld/examples/paintarena/README.md), which is the canonical example used by this
  package documentation and includes concrete runnables for every Coworld role.

Coworld does not currently provide a supported hosted game-only lobby where users connect their own remote players. Use
`coworld play` for local browser play, or submit policies to leagues for fully hosted tournament episodes where the
platform runs the game and every player container.

## Documentation Map

The Coworld docs are being reorganized. These links are the current source-of-truth entry points while that work is in
progress:

| Need | Current doc |
| ---- | ----------- |
| Understand what a complete Coworld is | [Coworld overview](src/coworld/docs/README.md) |
| Build and test a new Coworld end to end | [Authoring A Coworld](src/coworld/docs/AUTHORING.md) |
| Build or operate from recipes | [Coworld cookbook](COOKBOOK.md) |
| Understand manifest fields | [Manifest reference](src/coworld/docs/COWORLD_MANIFEST.md) |
| Understand roles and artifact flow | [Coworld overview](src/coworld/docs/README.md#roles) |
| Implement a game runnable | [Game role](src/coworld/docs/roles/GAME.md) |
| Implement or submit a player | [Player role](src/coworld/docs/roles/PLAYER.md) and [Coworld cookbook](COOKBOOK.md) |
| Call Bedrock / an LLM from a player | [Bedrock for players](src/coworld/docs/BEDROCK.md) |
| Implement supporting roles | [Reporter](src/coworld/docs/roles/REPORTER.md), [Commissioner](src/coworld/docs/roles/COMMISSIONER.md), [Grader](src/coworld/docs/roles/GRADER.md), [Diagnoser](src/coworld/docs/roles/DIAGNOSER.md), and [Optimizer](src/coworld/docs/roles/OPTIMIZER.md) |
| Start from installable templates | `coworld/templates` in the installed package |
| Rebuild with the current role source layout | [Rebuilding Coworlds After The Role Repo Move](src/coworld/docs/REBUILDING_COWORLDS.md) |
| Understand artifact contracts | [Artifact reference](src/coworld/docs/artifacts/README.md) |
| Consume episode artifacts as a unit | [Episode bundle reference](src/coworld/docs/artifacts/EPISODE_BUNDLE.md) |
| Understand the episode lifecycle | [Lifecycle overview](src/coworld/docs/LIFECYCLE.md) |
| Debug local or hosted execution | [Local runner](src/coworld/runner/RUNNER_README.md) and [Kubernetes runner](src/coworld/runner/KUBERNETES_RUNNER_README.md) |
| Start from the canonical example | [Paint Arena](src/coworld/examples/paintarena/README.md) |
| Look up exact CLI or API reference | `uv run coworld --help`, `uv run coworld <command> --help`, and Observatory OpenAPI |

Planned cleanup will shrink or move several of these pages into a smaller set of cookbook, lifecycle, runnable, and
artifact documents. Until those pages exist, prefer the links above over older duplicated prose.
