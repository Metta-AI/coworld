# AGENTS.md — coworld

Public CLI and Python package for Softmax v2 tournaments ("Coworlds"): download Coworlds, scaffold starter policies, run
local episodes, host live play sessions, upload game/policy containers, submit to leagues, and inspect standings, logs,
and replays. Depends on `softmax-cli` (workspace source) for auth; also uses `kubernetes`, `typer`, `websockets`, and
`pyarrow`. Published to PyPI.

## CLI

Installs a `coworld` entrypoint (`coworld.cli:app`, Typer):

```bash
uv run coworld --help
uv run coworld leagues                                   # list public leagues (needs `softmax login`)
uv run coworld download <coworld-name-or-id> --output-dir ./coworld
uv run coworld run-episode <manifest.json> <image:tag>   # local episode
uv run coworld play <manifest.json> [image|request.json] # interactive local play
uv run coworld build / certify / upload-coworld          # game-author loop
uv run coworld upload-policy / submit                     # player loop
uv run coworld hosted-game create|join                   # hosted browser play (subapp)
```

Auth-backed commands require `uv run softmax login` first (the `auth` extra pulls in `softmax-cli`).

## Tests

```bash
uv run metta pytest packages/coworld/tests -v
uv run metta pytest --changed
```

A `slow` marker is defined; the `test` extra adds `fastapi`, `uvicorn`, `numpy`, `pyarrow`, and `pytest-httpserver`.

## Lint

```bash
uv run metta lint --fix              # ruff (also runs via the Edit/Write hook)
```

## Source layout (`src/coworld/`)

- `cli.py`, `tournament_cli.py` — Typer command surface (local episodes, uploads, leagues, hosted play).
- `cli_support.py`, `api_client.py` — shared CLI helpers and the Softmax/Coworld API client.
- `certifier.py` — `coworld certify` smoke-test pipeline.
- `manifest_validation.py`, `schema_validation.py`, `manifest_uri.py` — manifest + schema validation.
- `bundle.py` — episode-bundle assembly (`COGAME_EPISODE_BUNDLE_URI`).
- `play.py`, `runner/` — local episode runner and request schema.
- `starter_policy.py`, `policies/` — packaged starter policy templates (`coworld make-policy`).
- `commissioner/`, `submit.py`, `upload.py` — league round-running and uploads.
- `examples/` — smallest complete Coworld (`paintarena`); `docs/roles/` — per-role contracts.

## Reference docs (`src/coworld/`)

- `COWORLD_README.md` — overview and concepts (also the published package readme).
- `CLI_README.md` — full command reference.
- `GAME_RUNTIME_README.md` — game-container runtime contract.
- `MANIFEST_README.md` — `coworld_manifest.json` field reference.
- `API_GUIDE.md`, `EPISODE_BUNDLE_README.md` — public API and bundle contracts.

## Gotchas

- Versioned via `setuptools_scm` off `coworld-v*` git tags (`fallback_version = 0.0.0`).
- The wheel's `package-data` deliberately **excludes** `Dockerfile`s and example READMEs: non-runtime edits must not
  change wheel content, or they invalidate Bazel action keys for every downstream `@pyenv` consumer. Keep that exclusion
  list in mind when adding example assets.
- Antfarm hosts Coworld game containers — the runtime contract is shared (`packages/antfarm`).
