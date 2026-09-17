# Coworld Schema Current State

## Source of truth

- Schema JSON: `packages/coworld/src/coworld/coworld_manifest_schema.json`
- Role docs: `packages/coworld/src/coworld/docs/roles/` (GAME.md, PLAYER.md, REPORTER.md, GRADER.md, DIAGNOSER.md,
  OPTIMIZER.md)
- Artifact docs: `packages/coworld/src/coworld/docs/artifacts/`

## Required top-level manifest fields

`game`, `player` (array, ≥1), `variants` (array, ≥1), `certification`

## Required game fields

`name`, `version`, `description`, `owner`, `config_schema`, `results_schema`, `runnable`, `protocols`, `docs`

`docs.readme` is required. `docs.pages[]` is optional.

## Runnable role spec shape (reporter entries have a separate reference shape)

Required: `type`, `id`, `name`, `description`, and exactly one of `image` or `file`. Only player entries accept `file`;
all players must match `game.player_runtime`. Optional: `run`, `env`, `resources`, `source_url`, `repository_url`.
Player files do not use `run`, `env`, or `resources`. `additionalProperties: false` — no extra fields allowed.

## Role sections

- `commissioner[]` — optional
- `reporter[]` — optional
- `grader[]` — optional
- `diagnoser[]` — optional (intended to become required)
- `optimizer[]` — optional (intended to become required)

## Player runtime selection

`game.player_runtime` defaults to `platform-hosted` (Observatory-hosted container players). `game-hosted` instead stages
a file per seat for execution inside the game. Both use Kubernetes hosted episodes. Read the
[runtime guide](https://github.com/Metta-AI/coworld/blob/main/src/coworld/docs/PLAYER_RUNTIMES.md) before choosing.
Local Metta source: `packages/coworld/src/coworld/docs/PLAYER_RUNTIMES.md`.

Game-hosted files use package-relative paths before upload and `sha256:` references afterward. Download restores bundled
files. The game owns the file format, execution limits, isolation, and per-seat output; there is no supplied player
sandbox, environment, or policy secret injection. Human seats, lobbies, hosted play, local `coworld play`, persistent
player runtimes, and analysis routes are unsupported.

## Key contracts by role

### Game

- HTTP/WS server on `COGAME_HOST:COGAME_PORT` (default 0.0.0.0:8080)
- Must serve: `/healthz`, `/client/player`, `/client/global`, `/client/replay`, `/player` WS, `/global` WS, `/replay` WS
- Replay mode: `COGAME_LOAD_REPLAY_URI` set
- `/client/replay` must auto-play and loop
- Writes results to `COGAME_RESULTS_URI`, replay to `COGAME_SAVE_REPLAY_URI`, or a terminal player failure to
  `COGAME_PLAYER_FAILURE_URI`
- `config_schema` must require a `tokens` string array with `minItems` and `maxItems`; equal bounds define a fixed slot
  count, while variable bounds require each token-free game config to carry `players` so its length defines the concrete
  slot count

### Player

- Platform-hosted: short-lived container, connects to `/player` through `COWORLD_PLAYER_WS_URL`; runner captures
  stdout/stderr.
- Game-hosted: game reads `COGAME_PLAYER_SEATS_URI`, executes each `file_uri`, and writes every seat's `log_uri`.
  `artifact_uri` and `player_status_uri` outputs are optional. Finish outputs and replay before writing results.
- Logs and artifacts are policy-scoped. Never leak private seat output into public game logs.
- Game-hosted certification requires a real log for every fixture slot. Every bundled player must be seated in both
  modes.
- File policies upload with `coworld upload-policy --file PATH`; they cannot carry container flags or secrets.
- Model calls for game-hosted seats originate in the game with `X-Coworld-Player-Slot: N` for correct attribution.

### Reporter

- Not a container (spec 0061): the manifest `reporter[]` section holds references — `{"reporter": "owner/name@version"}`
  for a platform reporter version, or `{"wasm": "./path.wasm", "id": ..., "attributes": ...}` for a wasm component the
  package builds and submits at upload
- Runs platform-side in the Bureau against the `softmax:reporter` wasm world; see `docs/roles/REPORTER.md`

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
