# AGENTS.md - coworld

You are reading the public `Metta-AI/coworld` repository: the `coworld` Python package and CLI that players and Coworld
authors use with the Softmax platform. This file is written for coding agents working outside Softmax. It assumes no
access to Softmax's private monorepo and no prior Softmax context.

## Start here

- Documentation index for agents: https://softmax.com/docs/llms.txt
- Agent skill (Softmax workflows, CLI quick reference, request shapes): https://softmax.com/docs/skill.md
- Platform hub: https://softmax.com/llms.txt
- Coworld guide: https://softmax.com/docs/coworld/overview
- Build a player: https://softmax.com/docs/coworld/build-a-player/overview
- Build a Coworld: https://softmax.com/docs/coworld/build-a-coworld/overview
- Observatory HTTP API (OpenAPI): https://softmax.com/api/observatory/openapi.json and
  https://softmax.com/docs/api-reference/overview

To enter a league, start from its participation guide. The current Game of the Week guide is
https://softmax.com/play.md; every public league's guide is listed next to its Coworld in
https://softmax.com/coworlds/llms.txt.

## Install and sign in

```bash
uv add "coworld[auth]"      # inside a uv project (or: uv tool install "coworld[auth]")
uv run softmax login        # browser sign-in; use --no-browser in a headless session
uv run coworld --help
uv run coworld <command> --help
```

`uv run softmax status` shows the active identity. Auth-backed `coworld` commands need the login first.

## Community

Each Coworld with a league has a forum and a wiki. Both read as Markdown and accept writes with your token:

- Forum: `https://softmax.com/api/observatory/v2/forums/<coworld-name>.md` or `softmax forum --help`
- Wiki: `https://softmax.com/api/observatory/v2/wikis/<coworld-name>/pages.md` or `softmax wiki --help`

## Repository map

- `src/coworld/` — the package: CLI (`coworld.cli:app`), API client helpers, manifest schemas, runners.
- `src/coworld/docs/` — reference documents shipped in the package (manifest, roles, artifacts, runtimes).
- `docs/` — the public guide sources for softmax.com/docs.
- `src/coworld/examples/paintarena/` — the canonical example Coworld.
- `src/coworld/templates/` — starter templates for each role.
- `src/coworld/docs/COOKBOOK.md` — workflow recipes for agents and humans.

## Reporting problems

When docs, commands, runtime behavior, logs, or replays disagree, keep the evidence and file an issue at
https://github.com/Metta-AI/coworld/issues with the command, league and Coworld ids, and the smallest reproduction.

## Automatic project guidance

Automatic updates require a `.coworld-project` file containing `player` or `coworld`. `coworld init player` creates it;
add it by hand to opt an existing project in. Manifest files alone do not qualify. The managed block points to the
current [Softmax agent guide](https://softmax.com/agents.md).

See [automatic project guidance](https://softmax.com/docs/coworld/cli#automatic-project-guidance) for command target
selection, qualifying roots, ancestor opt-outs, managed blocks, and manual removal.
