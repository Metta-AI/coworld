# Coworld

Coworld is where games become programmable arenas: worlds you can run locally, play in the browser, use to evaluate
players, and enter through league submissions. A good Coworld gives game authors a complete packaging contract and
gives player authors a clear target for building smarter agents.

The `coworld` package contains the public CLI, Python helpers, manifest types and schemas, runner tooling, and the
Paint Arena reference world.

Start with the [Coworld guide](https://docs.softmax.com/coworld/overview). The same public guide sources are available
in this repository under [`docs/`](docs/overview.mdx).

## What Is A Coworld?

A Coworld is a game environment built around a player-improvement loop. It combines a game, the players acting inside
it, and the evidence needed to understand each episode.

The core loop is simple: run an episode, inspect what happened, improve a player, and run again. The same Coworld can be
used for local development and hosted league competition.

Most readers should follow [Build a player](https://docs.softmax.com/coworld/build-a-player/overview). Coworld authors
should follow [Build a Coworld](https://docs.softmax.com/coworld/build-a-coworld/overview).

## Main Workflows

| Workflow | Start with |
| -------- | ---------- |
| Build or improve a player | [Build a player](https://docs.softmax.com/coworld/build-a-player/overview) |
| Call an LLM / Bedrock from a player | [Bedrock guide](https://docs.softmax.com/coworld/build-a-player/bedrock) and the exact [runtime contract](src/coworld/docs/BEDROCK.md) |
| Iterate against hosted opponents | [Improve a policy](https://docs.softmax.com/coworld/build-a-player/improve-a-policy) and `uv run coworld xp-request --help` |
| Size an old-vs-new hosted evaluation | [Cookbook: Size A Policy Field Study](COOKBOOK.md#size-a-policy-field-study) and `uv run coworld power-analysis --help` |
| Run and verify a player locally | [Package and smoke-test](https://docs.softmax.com/coworld/build-a-player/package-and-verify) |
| Inspect hosted logs, results, and replays | [Debug hosted episodes](https://docs.softmax.com/coworld/build-a-player/debug-hosted-episodes) |
| Discover reporters and what they produce | `uv run coworld reporters list` / `search <text>` / `show <rptr_...>` (add `--json` for machine output) |
| Save per-player debugging files after an episode | [Player artifact](src/coworld/docs/artifacts/PLAYER_ARTIFACT.md) and `uv run coworld episode-logs --help` |
| Author a new Coworld end to end | [Build a Coworld](https://docs.softmax.com/coworld/build-a-coworld/overview) |
| Build, certify, and upload a Coworld | [Build, certify, and upload](https://docs.softmax.com/coworld/build-a-coworld/build-certify-upload) |
| Audit Coworld upload workflows | [Cookbook: Automating uploads](COOKBOOK.md#automating-uploads) and `uv run coworld deploy-audit --owner Metta-AI` |
| Rebuild an existing Coworld after a role/source move | [Rebuilding Coworlds After The Role Repo Move](src/coworld/docs/REBUILDING_COWORLDS.md) |
| Understand package structure and manifest fields | [Manifest reference](src/coworld/docs/COWORLD_MANIFEST.md) |

## What This Package Provides

- CLI workflows for local play, local episode runs, certification, Coworld upload, policy upload/submission, league
  inspection, and artifact retrieval.
- Pydantic models and generated JSON schemas for Coworld manifests and runner episode requests.
- Local and Kubernetes runner code for executing Coworld episodes.
- Public API client helpers for coding agents that need to inspect leagues, rounds, episodes, replays, and uploaded
  Coworlds.
- Installable starter templates under `coworld/templates` for game, player, grader, diagnoser, and optimizer roles.
  Omit the commissioner template — Softmax leagues use the platform ladder
  ([Commissioner role](src/coworld/docs/roles/COMMISSIONER.md)). (Reporters are submittable wasm components, not
  containers; see the [Reporter role](src/coworld/docs/roles/REPORTER.md).)
- The [Paint Arena example](src/coworld/examples/paintarena/README.md), the canonical example for this package's docs.

Coworld does not currently provide a supported hosted game-only lobby where users connect their own remote players. Use
`coworld play` for local browser play, or submit policies to leagues for fully hosted tournament episodes where the
platform runs the game and every player container.

## Documentation Map

Public guides:

- [Softmax platform](https://docs.softmax.com/guides/platform-overview)
- [Coworld overview](https://docs.softmax.com/coworld/overview)
- [Build a player](https://docs.softmax.com/coworld/build-a-player/overview)
- [Build a Coworld](https://docs.softmax.com/coworld/build-a-coworld/overview)
- [Leagues, rounds, and episodes](https://docs.softmax.com/coworld/concepts/competition)

Technical references:

- [Coworld concept and contract map](src/coworld/docs/README.md)
- [Manifest semantics](src/coworld/docs/COWORLD_MANIFEST.md)
- [Role contracts](src/coworld/docs/README.md#roles)
- [Artifact contracts](src/coworld/docs/artifacts/README.md)
- [Coworld cookbook](COOKBOOK.md)
- [Paint Arena](src/coworld/examples/paintarena/README.md)

Use `uv run coworld --help` and `uv run coworld <command> --help` for the current CLI surface. Use the [Observatory
OpenAPI specification](https://softmax.com/api/observatory/openapi.json) for exact API request and response shapes.
