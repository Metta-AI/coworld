# Coworld Schema Current State

## Source of truth

- Schema JSON: `packages/coworld/src/coworld/coworld_manifest_schema.json`
- Role docs: `packages/coworld/src/coworld/docs/roles/` (GAME.md, PLAYER.md, REPORTER.md, GRADER.md, DIAGNOSER.md, OPTIMIZER.md)
- Artifact docs: `packages/coworld/src/coworld/docs/artifacts/`

## Required top-level manifest fields

`game`, `player` (array, ≥1), `variants` (array, ≥1), `certification`

## Required game fields

`name`, `version`, `description`, `owner`, `config_schema`, `results_schema`, `runnable`, `protocols`, `docs`

`docs.readme` is required. `docs.pages[]` is optional.

## Role spec shape (shared by all role arrays)

Required: `type`, `image`, `id`, `name`, `description`
Optional: `run`, `env`, `source_url`, `repository_url`
`additionalProperties: false` — no extra fields allowed.

## Role sections

- `commissioner[]` — optional
- `reporter[]` — optional
- `grader[]` — optional
- `diagnoser[]` — optional (intended to become required)
- `optimizer[]` — optional (intended to become required)

## Key contracts by role

### Game
- HTTP/WS server on `COGAME_HOST:COGAME_PORT` (default 0.0.0.0:8080)
- Must serve: `/healthz`, `/client/player`, `/client/global`, `/client/replay`, `/player` WS, `/global` WS, `/replay` WS
- Replay mode: `COGAME_LOAD_REPLAY_URI` set
- `/client/replay` must auto-play and loop
- Writes results to `COGAME_RESULTS_URI`, replay to `COGAME_SAVE_REPLAY_URI`
- `config_schema` must require a fixed-length `tokens` string array

### Player
- Short-lived, connects to game's `/player` WS via `COWORLD_PLAYER_WS_URL`
- stdout/stderr captured by runner as `logs/policy_agent_{slot}.log`
- Player logs are included in the episode bundle

### Reporter
- Reads `COGAME_EPISODE_BUNDLE_URI` (zip), writes zip to `COGAME_REPORT_URI`
- Report zip: manifest.json + renderable files + optional event_log.parquet + optional trace

### Grader
- Reads `COGAME_EPISODE_BUNDLE_URI`, writes JSON to `COGAME_GRADE_URI`
- Output: `{grader_id, score}` minimum

### Diagnoser
- Reads `COGAME_EPISODE_BUNDLE_URI` + `COGAME_TARGET_POLICY_URI`, writes zip to `COGAME_DIAGNOSIS_URI`
- Contract is tentative

### Optimizer
- Long-running workbench, NOT a one-shot container
- Invoked via `coworld optimize`; clones `repository_url` and runs locally
- Default: `Metta-AI/optimizers`
