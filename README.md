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

If you are building a complete Coworld, start with [Developing Coworlds](#developing-coworlds-work-in-progress).

## Developing Players (Work In Progress)

Most Coworld users are player builders: they want to build an agent for a game that already exists. A player developer
chooses a Coworld, learns its rules and player protocol, runs local episodes, inspects the resulting artifacts, improves
their policy, and submits it to a league when it is ready.

The player development user guide is still under construction. For now, use:

- [Player role](src/coworld/docs/roles/PLAYER.md) for the current player contract.
- [Coworld cookbook](COOKBOOK.md) for current player development recipes.
- [Paint Arena](src/coworld/examples/paintarena/README.md) as the canonical example world.

## Developing Coworlds (Work In Progress)

Coworld builders create the worlds that player developers target. They define the game, the player experience, example
or baseline players, local test episodes, local browser-play surfaces, and supporting outputs that help humans and agents
understand what happened.

The Coworld development user guide is still under construction. For now, start with the
[Paint Arena example](src/coworld/examples/paintarena/README.md) and use the [Documentation Map](#documentation-map) for
the current reference docs.

## Main Workflows

| Workflow | Start with |
| -------- | ---------- |
| Build or improve a player | [Cookbook: Upload And Submit A Player](COOKBOOK.md#upload-and-submit-a-player) and [Player role](src/coworld/docs/roles/PLAYER.md) |
| Run local episodes or browser play | [Cookbook: Build And Run Paint Arena Locally](COOKBOOK.md#build-and-run-paint-arena-locally) |
| Inspect league status, logs, results, and replays | [Cookbook: Watch Results And Find Episodes](COOKBOOK.md#watch-results-and-find-episodes) |
| Build, certify, and upload a Coworld | [Cookbook: Certify And Upload A Coworld](COOKBOOK.md#certify-and-upload-a-coworld) |
| Improve a policy in the optimizer workbench | `uv run coworld optimize` and [Optimizer role](src/coworld/docs/roles/OPTIMIZER.md) |
| Understand package structure and manifest fields | [Manifest reference](src/coworld/docs/COWORLD_MANIFEST.md) |

## What This Package Provides

- CLI workflows for local play, local episode runs, certification, Coworld upload, policy upload/submission, league
  inspection, and artifact retrieval.
- Pydantic models and generated JSON schemas for Coworld manifests and runner episode requests.
- Local and Kubernetes runner code for executing Coworld episodes.
- Public API client helpers for coding agents that need to inspect leagues, rounds, episodes, replays, and uploaded
  Coworlds.
- The [Paint Arena example](src/coworld/examples/paintarena/README.md), which is the canonical example used by this
  package documentation.

Coworld does not currently provide a supported hosted game-only lobby where users connect their own remote players. Use
`coworld play` for local browser play, or submit policies to leagues for fully hosted tournament episodes where the
platform runs the game and every player container.

## Documentation Map

The Coworld docs are being reorganized. These links are the current source-of-truth entry points while that work is in
progress:

| Need | Current doc |
| ---- | ----------- |
| Understand what a complete Coworld is | [Coworld overview](src/coworld/docs/README.md) |
| Build or operate from recipes | [Coworld cookbook](COOKBOOK.md) |
| Understand manifest fields | [Manifest reference](src/coworld/docs/COWORLD_MANIFEST.md) |
| Understand roles and artifact flow | [Coworld overview](src/coworld/docs/README.md#roles) |
| Implement a game runnable | [Game role](src/coworld/docs/roles/GAME.md) |
| Implement or submit a player | [Player role](src/coworld/docs/roles/PLAYER.md) and [Coworld cookbook](COOKBOOK.md) |
| Understand artifact contracts | [Artifact reference](src/coworld/docs/artifacts/README.md) |
| Consume episode artifacts as a unit | [Episode bundle reference](src/coworld/docs/artifacts/EPISODE_BUNDLE.md) |
| Understand the episode lifecycle | [Lifecycle overview](src/coworld/docs/LIFECYCLE.md) |
| Debug local or hosted execution | [Local runner](src/coworld/runner/RUNNER_README.md) and [Kubernetes runner](src/coworld/runner/KUBERNETES_RUNNER_README.md) |
| Start from the canonical example | [Paint Arena](src/coworld/examples/paintarena/README.md) |
| Look up exact CLI or API reference | `uv run coworld --help`, `uv run coworld <command> --help`, and Observatory OpenAPI |

Planned cleanup will shrink or move several of these pages into a smaller set of cookbook, lifecycle, runnable, and
artifact documents. Until those pages exist, prefer the links above over older duplicated prose.
