# AGENTS.md - coworld

Public CLI and Python package for Softmax v2 tournaments ("Coworlds"). This package owns the user-facing `coworld`
entrypoint, local episode/play tooling, Coworld uploads, policy uploads/submission helpers, the Paint Arena reference
Coworld, and the public Coworld docs shipped with the package. It depends on `softmax-cli` for auth-backed commands.

## Coworlds Expert Agent

A distributable Claude Code agent for coworld developers is available at
[`docs/coworlds-expert-agent/`](docs/coworlds-expert-agent/). It knows coworld design principles
(the derivation chain, grader philosophy, player policy design, schema contracts) and can be
installed into any coworld project's `.claude/agents/` directory. See its
[README](docs/coworlds-expert-agent/README.md) for install instructions.

## Before Editing

- Read this file, `LESSONS.md`, the package [README](README.md), and the [Coworld docs map](src/coworld/docs/README.md)
  before changing user-facing Coworld behavior or docs.
- Keep package docs public-package-facing. Avoid private Metta backend paths unless the document is intentionally
  explaining a platform integration boundary.
- Treat Paint Arena under `src/coworld/examples/paintarena/` as the canonical in-tree example.

## CLI

The package installs the Typer app at `coworld.cli:app`:

```bash
uv run coworld --help
uv run coworld leagues
uv run coworld download <coworld-name-or-id> --output-dir ./coworld
uv run coworld run-episode <manifest.json> <image:tag>
uv run coworld scrimmage <manifest-or-id> [request.json|image...] [-n N]
uv run coworld play <manifest.json> [image|request.json]
uv run coworld build / certify / upload-coworld
uv run coworld upload-policy / submit
```

Auth-backed commands require `uv run softmax login` first. The `auth` extra pulls in `softmax-cli`.

## Validation

Use the narrowest check that covers the touched surface, then broaden when changing shared contracts:

```bash
uv run metta pytest packages/coworld/tests/test_types.py -v
uv run metta pytest packages/coworld/tests -v
uv run metta pytest --changed
uv run metta lint --fix
```

When changing manifest Pydantic models or generated schema files, update `types.py` first and regenerate the checked-in
schema JSON:

```bash
uv run --project packages/coworld python packages/coworld/scripts/generate_coworld_schemas.py
uv run metta pytest packages/coworld/tests/test_types.py -v
```

Do not hand-edit `src/coworld/coworld_manifest_schema.json` or `src/coworld/runner/episode_request_schema.json` as the
source of truth. They are generated docs and `$schema` targets; `test_types.py` checks that they match `types.py`.

## Source Layout

- `src/coworld/cli.py`, `tournament_cli.py` - Typer command surface for local episodes, uploads, leagues, and hosted
  tournament inspection.
- `src/coworld/cli_support.py`, `api_client.py` - shared CLI helpers and the Softmax/Coworld API client.
- `src/coworld/certifier.py` - `coworld certify` smoke-test pipeline.
- `src/coworld/manifest_validation.py`, `schema_validation.py`, `manifest_uri.py` - manifest and schema validation.
- `src/coworld/bundle.py` - episode-bundle assembly around `COGAME_EPISODE_BUNDLE_URI`.
- `src/coworld/play.py`, `src/coworld/runner/` - local play, local episode runner, and hosted-runner contracts.
- `src/coworld/commissioner/`, `submit.py`, `upload.py` - league round-running, submission, and upload support.
- `src/coworld/examples/paintarena/` - smallest complete Coworld and reference implementation.

## Documentation Map

- [README.md](README.md) - package landing page, player-first orientation, and navigation.
- [COOKBOOK.md](COOKBOOK.md) - task recipes for local play, policy upload/submission, tournament results, and
  Coworld upload.
- [src/coworld/docs/README.md](src/coworld/docs/README.md) - Coworld concept map, role statuses, artifact flow, and
  cross-links.
- [src/coworld/docs/COWORLD_MANIFEST.md](src/coworld/docs/COWORLD_MANIFEST.md) - manifest semantics and schema source
  of truth.
- [src/coworld/docs/LIFECYCLE.md](src/coworld/docs/LIFECYCLE.md) - local and hosted episode lifecycle.
- `src/coworld/docs/roles/*.md` - per-role contracts.
- `src/coworld/docs/artifacts/*.md` - artifact contracts.
- `src/coworld/runner/RUNNER_README.md` and `src/coworld/runner/KUBERNETES_RUNNER_README.md` - runner-specific
  behavior.

## Manifest And Role Contracts

- The base schema currently requires `game` and `player`. `reporter`, `commissioner`, `grader`, `diagnoser`, and
  `optimizer` are optional in the base schema; `diagnoser` and `optimizer` are marked future-required in generated
  schema metadata.
- Role semantics belong in `src/coworld/docs/roles/`. Field-level manifest shape belongs in `src/coworld/types.py` and
  the generated schema JSON, not in duplicated Markdown tables.
- Manifest role changes usually need matching updates to role docs, Paint Arena templates, generated schemas,
  certifier/runner tests, and any README links that name the role.
- Do not describe `coworld hosted-game` as a supported player workflow unless product/runtime support is restored.
  Current hosted execution means tournament jobs where the platform runs the game and every player container.

## Package Data Gotchas

- Versioning uses `setuptools_scm` from `coworld-v*` git tags (`fallback_version = "0.0.0"`).
- `pyproject.toml` deliberately excludes Dockerfiles and example READMEs from wheel package data. Non-runtime example
  edits should not change wheel content or Bazel action keys for downstream `@pyenv` consumers.
- Antfarm hosts Coworld game containers; keep `packages/antfarm/README.md` aligned when the game-container contract
  changes.
