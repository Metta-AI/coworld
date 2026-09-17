# Choose a Player Runtime

Choose `game.player_runtime` before implementing a new Coworld's players. Both modes run hosted episodes on Observatory
using Kubernetes (`execution_backend=k8s`). This field selects who executes each player, not where the game is hosted.
“Observatory-hosted players” means `platform-hosted` in the manifest; `observatory-hosted` is not a valid value.

## Compare the two modes

| Decision                       | `platform-hosted` (default)                                                              | `game-hosted`                                                                                                       |
| ------------------------------ | ---------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| Player artifact                | Docker image (`docker-img` policy)                                                       | File or directory packed as a zip (`player-file` policy)                                                            |
| Packaging                      | Build a `linux/amd64` player image; 512 MiB bundled image cap; 5 GiB submitted image cap | Prepare a game-defined file or directory; 100 MiB packed cap for bundled and submitted files                        |
| Startup                        | Pull an image and start a container per seat within the player connection deadline       | Stage and verify seat files before starting the game; game owns player initialization                               |
| Bundled manifest entry         | `player[].image`                                                                         | `player[].file`                                                                                                     |
| Execution                      | Runner starts a container per seat; hosted runs use child pods                           | Game loads every seat's file inside its own container                                                               |
| Player interface               | Game-defined WebSocket protocol at `/player`; runner supplies `COWORLD_PLAYER_WS_URL`    | Game-defined file format, entrypoint, and execution protocol; runner supplies `COGAME_PLAYER_SEATS_URI` to the game |
| Resources and isolation        | Separate player containers, with platform resource controls                              | Game resources cover all seats; game author owns player isolation, scheduling, and execution limits                 |
| Policy configuration           | Player `run`, public environment, and policy-scoped secrets                              | No policy process environment or secrets; game defines configuration inside the file format                         |
| Player code visibility         | Game does not receive player image bytes                                                 | Game author controls code that can read or copy every submitted file                                                |
| Logs and artifacts             | Runner captures player logs; player uploads its optional zip                             | Game writes separate seat logs and optional zips                                                                    |
| Human and persistent workflows | Human seats, lobbies, hosted play sessions, and persistent player runtimes               | Episode-only; these workflows are unavailable                                                                       |

## Match the runtime to the game

Choose based on the interface and responsibilities you want to support:

| Requirement                                                                      | Fit                                                                                         |
| -------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| Submitters bring their own language runtime or dependencies                      | `platform-hosted`: each player packages its environment in an image.                        |
| Players need policy-scoped secrets, human play, or persistent player runtimes    | `platform-hosted`: these use existing platform workflows.                                   |
| Submitters should upload player files without building or pushing a player image | `game-hosted`: simpler player packaging, within the game-provided runtime and dependencies. |
| The game accepts a defined artifact, such as a ruleset, script, or model weights | `game-hosted`: the game supplies the loader and execution environment.                      |
| Player actions need direct in-game execution instead of a WebSocket exchange     | `game-hosted`: the game controls invocation and scheduling.                                 |

Platform-hosted authors implement the WebSocket protocol and handle container startup, connection deadlines, and
per-seat resource needs. Game-hosted authors implement file validation and execution budgets, and enforce isolation
where artifacts execute untrusted code. Neither choice guarantees better performance; measure the relevant workload.
Changing the mode does not convert existing policies.

## Contracts every Coworld keeps

Both modes still need the [game HTTP/WebSocket contract](roles/GAME.md), including `/healthz`, the global viewer and
WebSocket Ping/Pong behavior. Choosing game-hosted players does not remove the game routes or the certification probes.
Config schemas still require runner-injected `tokens` with seat bounds. Results still require one score per slot, replay
bytes remain required, and replay uses either the game container or a declared static viewer.

Read the [manifest reference](COWORLD_MANIFEST.md#player-runtime-and-artifact-pairing), [game role](roles/GAME.md),
[player role](roles/PLAYER.md), and [lifecycle](LIFECYCLE.md). The manifest examples are fragments, not complete
packages. Validate the complete manifest with Coworld tooling: Pydantic validators enforce image/file pairing beyond
what the generated JSON Schema expresses.

Both modes require a game image. Local episodes require Docker. Hosted platform-hosted player pods request 250m CPU /
256Mi memory by default; game-hosted seats share the game's allocation. These are requests, not execution limits. See
[runtime resource controls](../runner/KUBERNETES_RUNNER_README.md#hosted-resource-baseline).

## Implement platform-hosted players

Use the [player contract](roles/PLAYER.md#platform-hosted-players) for startup, WebSocket configuration, environment,
logs, and artifact uploads. Start from the [Paint Arena example](../examples/paintarena/README.md). Document
observations, actions, connection deadlines, and failure behavior in `game.protocols.player`. Seat every bundled player
in certification and test both the game and player containers through a complete episode.

## Implement game-hosted players

1. Set `game.player_runtime` to `game-hosted`. Give every bundled player exactly one package-relative `file`, and no
   `image`. Only player roles accept files; the game remains an image-backed runnable.
2. Specify the accepted file format, entrypoint, observation/action interface, dependency availability, and versioning
   in `game.protocols.player` and the game README. Document per-seat time, memory, filesystem, and network boundaries,
   invalid-file behavior, and the fallback or terminal failure rule. Treat submitted bytes as untrusted.
3. Read the [seats document](artifacts/PLAYER_SEATS.md) at `COGAME_PLAYER_SEATS_URI`. Use its slot numbers and URIs; do
   not infer a language from the staged filename, which is simply `file`. The trusted hosted init container verifies
   file size and SHA-256 before game startup. The game receives local paths, not signed download capabilities.
4. Execute each seat under the game-defined contract. Write every seat's `log_uri`, even for an empty log. Keep private
   player output out of public game stdout/stderr. Optionally write a zip at `artifact_uri` and diagnostic status at
   `player_status_uri`.
5. Finish and close replay, logs, artifacts, and status before publishing results at `COGAME_RESULTS_URI`. Results are
   the completion marker; collection does not wait for the game server to exit. For a terminal seat fault, write
   [GamePlayerFailure](roles/GAME.md#contract) to `COGAME_PLAYER_FAILURE_URI` instead of successful results. Diagnostic
   [player status](artifacts/PLAYER_STATUS.md) alone never assigns fault or changes the outcome.
6. Seat every bundled player in certification. Game-hosted certification requires a real log for every fixture slot; the
   runner's missing-log placeholder fails that check. Also test invalid player files, execution limits, isolation, and
   privacy with game-owned tests: platform certification does not prove those properties.

Input files are capped at **100 MiB** (104,857,600 bytes). Directories become deterministic zips; symlinks and package
escapes are rejected. The cap applies to packed bytes, so the game must bound extraction and execution itself. Hosted
output limits are **10 MiB per seat log** (truncated), **200 MiB per optional artifact** (oversized files skipped), and
**1 MiB for optional status** (invalid or oversized data discarded). See the [artifact contracts](artifacts/README.md)
for schemas and collection behavior.

## Build, test, upload, and download

The same author commands serve both modes:

```bash
uv run coworld build --version 0.1.0
uv run coworld run-episode dist/coworld_manifest.json
uv run coworld certify dist/coworld_manifest.json
uv run coworld upload-coworld dist/coworld_manifest.json --wait-certification
```

Build copies bundled player files into the output package; they need no Compose player service. Upload hashes and stores
them, replacing local paths with `sha256:` references. Download restores bundled files under `player-files/` and
rewrites the manifest to local paths:

```bash
uv run coworld download <coworld-name-or-id> --output-dir ./downloaded
```

Use the downloaded manifest path printed by the command for local episodes. Game-hosted `run-episode` accepts either no
overrides (use bundled players), or exactly one file/directory path per seat. For a two-seat game:

```bash
uv run coworld run-episode ./downloaded/<coworld-id>/coworld_manifest.json ./players/a.py ./players/b.py
uv run coworld upload-policy --file ./players/a.py --name my-file-player
```

Repeat a path explicitly to seat the same file twice. A single file override is not broadcast across multiple seats. Do
not pass an episode-request JSON as a game-hosted positional argument: it is interpreted as player bytes. `run-episode`
rejects player `--run`, `--secret-env`, and local Bedrock flags in this mode. `coworld play` and `coworld scrimmage` are
not game-hosted validation paths; use headless episodes, certification, and replay inspection. See the
[cookbook](COOKBOOK.md) for the full workflows, including file upload APIs.

For submitted policies, upload with `--file` rather than an image. File uploads reject `--run`, `--secret-env`,
`--use-bedrock`, and `--bedrock-model`. Submit the returned version through the normal league workflow. The target
Coworld must accept the policy kind: league submission rejects mismatches; episode hydration records `hydration_failed`
without launching a pod. Submitted policies are not exposed through Coworld downloads. Bundled players of either kind
are distributed publicly; see the comparison's code-visibility row for what the game receives during execution.

## Model calls and diagnostics

For game-hosted players, the game makes model calls through its hosted sidecar and attaches `X-Coworld-Player-Slot: N`
for seat `N`. That header assigns spend, telemetry, and request-rate accounting to the seat. Headerless requests stay
game-attributed and do not consume a player's spend ceiling. See [Bedrock](BEDROCK.md) and the
[game LLM contract](roles/GAME.md#bedrock-and-aws-access). File-policy upload flags cannot configure a player sidecar.

For platform-hosted players, startup failures include `player_error` and retryable `player_never_started`. Player pod
failures remain diagnostic until timeout unless the game declares a player failure. See
[player execution](../runner/KUBERNETES_RUNNER_README.md#player-execution) for startup deadlines and attribution.

A failed file download (`player_file_unavailable`) or digest/size mismatch (`player_file_mismatch`) is a platform
failure. Worker or init-container out-of-memory is `worker_oom`; game-container out-of-memory is `oom` and blames the
Coworld in game-hosted mode. Seat blame requires a game-declared player failure. Inspect
[error info](artifacts/ERROR_INFO.md), seat logs, status, and replay together.

## Reading paths

- Authors: [authoring guide](AUTHORING.md) → [manifest](COWORLD_MANIFEST.md) → [game](roles/GAME.md) →
  [seats](artifacts/PLAYER_SEATS.md) → [cookbook](COOKBOOK.md).
- Player builders: [player contract](roles/PLAYER.md) → the target game's `game.protocols.player` and `game.docs.readme`
  → [upload and local-run recipes](COOKBOOK.md).
- Runtime maintainers: [local runner](../runner/RUNNER_README.md) and
  [Kubernetes runner](../runner/KUBERNETES_RUNNER_README.md).
