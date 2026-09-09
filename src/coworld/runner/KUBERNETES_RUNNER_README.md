# Coworld Kubernetes Runner

`coworld.runner.kubernetes_runner` is the Kubernetes entrypoint for one Coworld episode. It replaces Docker-in-Docker
by running the game as an ordinary container and selecting one of two player execution paths.

The parent Kubernetes `Job` owns the game and coordinator containers. In `platform-hosted` mode, the coordinator creates
one child pod per player. In `game-hosted` mode, the trusted init container stages player files and the game executes
them. The coordinator then uploads the configured artifacts.

Unlike the local Docker runner, the Kubernetes runner does not publish arbitrary extra host TCP ports from the game
container. `COWORLD_LOCAL_EXTRA_PORTS` is local-runner-only today.

## Hosted resource baseline

Hosted Kubernetes runners schedule each episode component with explicit resource requests so the scheduler reserves real
capacity:

| Component               | Resource request          |
| ----------------------- | ------------------------- |
| Game container          | 1 CPU and 512Mi memory    |
| Runner worker container | 250m CPU and 256Mi memory |
| Each platform-hosted player container | 250m CPU and 256Mi memory |
| Replay container        | 2 CPU and 2Gi memory      |

These are scheduling **requests**, not CPU or memory limits. A container may use more if the node has spare capacity,
but game and player authors should treat the requested capacity as the portable baseline available in hosted runs.
Hosted deployments pass player requests through `COWORLD_PLAYER_CPU_REQUEST` and `COWORLD_PLAYER_MEMORY_REQUEST`; if
those env vars are omitted in a direct runner invocation, the coordinator falls back to 2 CPU and 2Gi memory per player
pod.

A player pod gets **no CPU limit by default**, so it may burst to every core on the node it lands on — meaning a policy
that reads `os.cpu_count()`/`nproc` sees 8/12/16 cores depending on placement. A Coworld that wants deterministic,
node-size-independent player compute declares `player.resources.limits.cpu` in its manifest. The backend forwards it as
`COWORLD_PLAYER_CPU_LIMIT`, and the worker then (a) sets that as the player container's CPU limit and (b) pins the
player's math-library thread pools (`OMP_NUM_THREADS`/`MKL_NUM_THREADS`/`OPENBLAS_NUM_THREADS`/`NUMEXPR_NUM_THREADS`) to
`floor(limit)` cores so the player behaves like an N-core box on any node. The player image's own thread-env wins if it
sets these explicitly.

A game pod similarly gets **no CPU or memory limit by default**. A Coworld that wants a hard compute ceiling on the
game container declares `game.runnable.resources.limits.cpu` and/or `game.runnable.resources.limits.memory` in its manifest; the backend
clamps each declared field to its own bound envelope and applies it to the game container's `V1Container.resources`.
Unlike the player CPU limit, no math-library thread-pool pinning happens for the game role — that convention is
player/ML-policy specific. A declared limit must resolve to at least as much as that field's resolved request (itself
possibly the role default, when the request is omitted): Kubernetes cannot schedule a pod whose limit is below its
request, so registration rejects a manifest whose game limit would undercut its game request.

Per-player resource settings apply only to platform-hosted child pods. Game-hosted player execution consumes the game
container's requested and limited resources. Authors must size the game for the full roster.

Hosted episode Jobs have a 20 minute active deadline. The coordinator's per-episode wait defaults to
`COWORLD_TIMEOUT_SECONDS=3600`; hosted dispatch currently sets the Kubernetes Job deadline to 20 minutes and gives
presigned artifact URLs one extra hour of validity. A game may end an episode early by writing a typed
`player_failure.json` to `COGAME_PLAYER_FAILURE_URI`; otherwise player pod failures remain diagnostic until the episode
times out.

## Parent Job Shape

The parent Job has:

- `coworld-init-config`: writes the concrete game config and tokens. For game-hosted mode, it downloads, verifies, and
  writes one player file at a time. It writes `player_seats.json` after every slot is staged.
- `game`: regular non-restarting container that runs `manifest.game.runnable.image`, listens on port `8080`, and has a
  TCP liveness probe against the worker's health port (`9090`) so the kubelet stops it when the worker exits.
- `worker`: regular Job container that runs the Kubernetes coordinator and holds a TCP health port (`9090`) open for its
  whole lifetime.
- `coworld-workdir`: an `emptyDir` volume mounted into all parent containers.

The game receives URI-based artifact environment variables. Today the app backend supplies `file://` URIs inside
`COWORLD_WORKDIR` so the worker can validate results and upload hosted artifacts, but the game contract is URI-based
rather than path-based. The worker reaches the game locally for health checks and creates a ClusterIP Service so player
pods can connect back to the game. On exit — success or failure — the worker writes runner error info, collects logs,
and deletes any child player pods and Service. Because the worker holds a TCP health port open for its whole lifetime
and the game container liveness-probes that port, the kubelet stops the non-restarting game container whenever the
worker exits (timeout, crash, or OOM); the app backend deletes the parent Job. Failure diagnostics after error info are
best-effort, so a log, player-artifact, or timing upload failure cannot replace the episode failure. This couples the
game's lifetime to the worker without restarting the game on its own crash or exposing worker environment variables
through a shared process namespace.

## Commands

```bash
python -m coworld.runner.kubernetes_runner init-config
python -m coworld.runner.kubernetes_runner run-core-sidecars-v1
```

`init-config` and `run-core-sidecars-v1` are separate commands because Kubernetes init containers must finish before
the game and worker containers start. The versioned run command makes mixed coordinator/backend deployments fail
closed instead of silently bypassing the core sidecars.

## Required Inputs

Both commands require:

```bash
JOB_SPEC_URI
COWORLD_WORKDIR=/coworld
```

`run-core-sidecars-v1` also requires:

```bash
JOB_ID
JOB_NAME
JOB_NAMESPACE
COWORLD_SERVICE_NAME
POD_NAME
POD_UID
```

For a game-hosted init container, `PLAYER_FILE_URLS` is required. It is a JSON object mapping every zero-based slot to
a trusted download URL. Its key set must equal `0..len(players)-1`; an absent variable, missing slots, or extra slots
are `config_error`.

`JOB_SPEC_URI` points to a JSON `CoworldEpisodeJobSpec`:

```json
{
  "manifest": {
    "game": {
      "player_runtime": "platform-hosted",
      "runnable": {
        "image": "example-game:latest",
        "run": ["python", "/app/game/server.py"],
        "env": {}
      },
      "config_schema": {},
      "results_schema": {}
    }
  },
  "game_config": { "map": "default", "players": [{ "name": "policy:v1" }] },
  "players": [
    {
      "image": "example-player:latest",
      "run": ["python", "/app/player.py"],
      "env": {}
    }
  ],
  "episode_tags": {}
}
```

A game-hosted spec uses `"player_runtime": "game-hosted"` and replaces every player runnable with:

```json
{
  "type": "player-file",
  "content_hash": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "size_bytes": 12345
}
```

The file is read from `policies/files/<content_hash>`; the key is derived, never carried. This is the only payload
shape consumed by the coordinator. Backend bookkeeping such as the uploaded Coworld ID or
manifest hash lives in the backend's stored job payload and is converted out before `spec.json` is uploaded. Runner
specs do not carry backend-owned display-name metadata. Hosted dispatch injects resolved player names only into
`game_config.players[].name`, and only when the game declares that field.

## Player Execution

### Platform-hosted player pods

The coordinator creates one pod per player:

- image: `players[].image`
- command/args: `players[].run`
- env: `players[].env`
- resource requests: 250m CPU and 256Mi memory in hosted jobs
- `COWORLD_PLAYER_WS_URL`: points at the parent game's Kubernetes Service.
- `COWORLD_PLAYER_ARTIFACT_UPLOAD_URL` (optional): a `PUT` URL for one artifact `.zip` object per slot (max 200 MiB).
  The coordinator forwards each slot's target from `PLAYER_ARTIFACT_UPLOAD_URLS` (see Outputs). The player may replace
  that object with newer checkpoints during the episode but must finish the last upload before pod teardown. See
  [player artifact](../docs/artifacts/PLAYER_ARTIFACT.md).

The player query string includes only the generated slot token and slot index.

Each slot gets exactly one player pod generation during an episode. The
coordinator does not replace a waiting or vanished pod because Kubernetes
status may lag a process that has already acquired its one-shot game slot; a
replacement with the same credential could then be rejected as a duplicate.
`player_never_started` remains infrastructure-retryable, so recovery creates a
fresh episode with a fresh game and fresh slot credentials.

After creating player pods, the coordinator opens the global viewer websocket and holds it open while waiting for every
`player` container to start. The deadline is the minimum of `game_config.player_connect_timeout_seconds` (default 180s)
and `COWORLD_TIMEOUT_SECONDS`. A no-blame wait such as `ContainerCreating` retains the full budget. Policy failures
remain `player_error`; exhausting the start deadline is retryable `player_never_started`. A missing pod after startup
is inconclusive because Kubernetes may have reaped it.

The `address` query parameter is only for browser client pages served through an HTTP proxy, such as hosted play. The
Kubernetes runner does not use `address` for policy containers: `COWORLD_PLAYER_WS_URL` is the direct game websocket URL
and already includes the required `slot` and `token` query params.

### Game-hosted player files

The init container downloads each URL through trusted runner I/O. It verifies the declared byte length and lowercase
SHA-256 digest before writing `/coworld/players/{slot}/file`. Download failure is `player_file_unavailable`; a size or
digest mismatch is `player_file_mismatch`. Both fail before the game starts and never blame a policy seat.

The init container writes [`player_seats.json`](../docs/artifacts/PLAYER_SEATS.md) and the game receives
`COGAME_PLAYER_SEATS_URI=file:///coworld/player_seats.json`. No player pod, Service, WebSocket URL, per-player resources,
or policy secret environment exists in this mode.

For game-hosted jobs, `results.json` is the completion marker. The game must finish every seat log, seat artifact, and
`player_status.json` before writing results. The worker begins collection when results and the required replay exist;
the long-running game server does not need to exit.

## Game Container URIs

The app backend starts the game container with:

```bash
COGAME_HOST=0.0.0.0
COGAME_PORT=8080
COGAME_CONFIG_URI=file:///coworld/config.json
COGAME_RESULTS_URI=file:///coworld/results.json
COGAME_SAVE_REPLAY_URI=file:///coworld/replay
COGAME_PLAYER_FAILURE_URI=file:///coworld/player_failure.json
```

Game-hosted jobs also set:

```bash
COGAME_PLAYER_SEATS_URI=file:///coworld/player_seats.json
```

The game binds its HTTP and websocket server to `COGAME_HOST:COGAME_PORT`. `coworld-init-config` writes
`COGAME_CONFIG_URI` before the game starts. The game writes results and the replay to their supplied URIs. When the
game's own rules make a player failure terminal, it may instead write a `GamePlayerFailure` to
`COGAME_PLAYER_FAILURE_URI`. The worker validates these game outputs and remains the sole producer of the hosted
artifacts listed below.

## Optional Inputs

```bash
COWORLD_TIMEOUT_SECONDS=3600
COWORLD_WORKLOAD_TYPE=coworld-jobs
COWORLD_CAPACITY_TYPE=on-demand
COWORLD_PLAYER_CPU_REQUEST=250m
COWORLD_PLAYER_MEMORY_REQUEST=256Mi
COWORLD_PLAYER_CPU_LIMIT=8
LOG_LEVEL=...
```

`COWORLD_WORKLOAD_TYPE` controls the node selector and toleration applied to child player pods. In production the app
backend also applies the same workload-type selector and toleration to the parent Job. `COWORLD_CAPACITY_TYPE`
optionally adds a Karpenter capacity-type node selector, such as `on-demand`, to the parent Job and child player pods.
`COWORLD_PLAYER_CPU_REQUEST` and `COWORLD_PLAYER_MEMORY_REQUEST` override the resource requests applied to each child
player pod. `COWORLD_PLAYER_CPU_LIMIT` (empty/unset means no limit) sets a hard CPU ceiling on each child player pod and
pins its math-library thread pools to `floor(limit)` cores. `COWORLD_TIMEOUT_SECONDS` controls coordinator waits inside
the Job; the hosted parent Job also has its own 20 minute Kubernetes active deadline.

The three `COWORLD_PLAYER_*` resource variables are ignored when no player pods exist.

## Output URIs

The runner uploads each episode artifact to a separate URI. There is no single bundled output URI — bundling is a
consumption-time concern handled by the bundling layer; see
[artifacts/EPISODE_BUNDLE.md](../docs/artifacts/EPISODE_BUNDLE.md).

All output environment variables are optional for platform-hosted jobs, and hosted jobs normally provide them. A
game-hosted job must also provide `PLAYER_ARTIFACT_UPLOAD_URLS` (the dispatcher always does); the worker reads it after
a successful episode.

```bash
RESULTS_URI
REPLAY_URI
DEBUG_URI
ERROR_INFO_URI
PLAYER_STATUS_URI
POLICY_LOG_URLS
PLAYER_ARTIFACT_UPLOAD_URLS
```

Outputs:

- `RESULTS_URI`: game-defined `results.json`, validated against `manifest.game.results_schema`.
- `REPLAY_URI`: raw replay uploaded as `replay.replay`. Hosted upload and the hosted replay viewer both consume the
  game-owned bytes directly.
- `DEBUG_URI`: zip of the runner's `logs/` directory, containing game container stdout/stderr (`game.stdout.log`,
  `game.stderr.log`) plus any per-player log files (`policy_agent_{slot}.log`) the coordinator captured. Game container
  stdout/stderr is **public** to anyone with episode access — game authors must not write secrets or private information
  to those streams.
- `ERROR_INFO_URI`: typed failure JSON written by the coordinator. A game-declared `player_failure.json` is an input to
  the coordinator, not this final hosted artifact.
- `PLAYER_STATUS_URI`: `player_status.json` snapshot. The runner writes it before platform-hosted pod teardown. A
  game-hosted game may write it through the seats document. Each
  slot is `running`, `exited`, `not_started`, or `unavailable`; exited slots retain their exit code, Kubernetes reason,
  and finish time. This is process-lifecycle evidence, not a claim that an exit was successful or proof of the
  game-level WebSocket disconnect reason. An oversized game-authored file exceeds 1 MiB and is discarded as invalid.
- `POLICY_LOG_URLS`: JSON object mapping each player slot to a destination URI. Each log is uploaded from
  `policy_agent_{slot}.log`. Platform-hosted logs contain player-container output; game-hosted logs are game-written.
  Each upload is capped at 10 MiB and receives a trailing truncation marker when the source is longer. Player logs are also
  included in `DEBUG_URI`'s zip; `POLICY_LOG_URLS` exposes them individually for per-player consumption.
- `PLAYER_ARTIFACT_UPLOAD_URLS`: JSON object mapping each player slot to a presigned `PUT` target. The coordinator
  exposes each target through `COWORLD_PLAYER_ARTIFACT_UPLOAD_URL` for platform-hosted pods. In game-hosted mode, it
  uploads each non-empty `policy_artifact_{slot}.zip` after the game writes `results.json`. Files over 200 MiB are
  skipped. Each final upload gets one attempt with the initial file size as `Content-Length`; growth or upload failure
  skips that seat without changing the episode outcome. See
  [player artifact](../docs/artifacts/PLAYER_ARTIFACT.md).

Per-player logs are diagnostic only. After the game has produced valid results, the coordinator reads the last 10,000
combined stdout/stderr lines from player pods whose `player` container has started and skips pods whose container is
still waiting, such as `ContainerCreating`. Missing player logs do not fail an otherwise successful episode; result and
replay upload remain the source of truth for episode success.
The adjacent `player_status.json` artifact preserves the structured pod state that existed at that same observation
point, separately from game-authored scores. Authorized episode consumers can fetch it from
`/v2/episode-requests/{episode_request_id}/artifacts/player-status`.
Kubernetes API transport failures during log collection are written into the
corresponding diagnostic log artifact and likewise do not change the episode
outcome.

For game-hosted output, an absent slot log becomes a diagnostic placeholder. Optional `player_status.json` is capped at
1 MiB and validated against the version 1 schema; oversized or invalid JSON is logged, deleted, and not uploaded.
Neither condition fails the episode.

There is no separate hosted media artifact for videos, screenshots, or rich human-readable reports in the episode runner
path. Put compact, replay-critical bytes in the replay artifact, keep `results.json` small and schema-valid, and use
platform reporter runs or support-role artifacts for larger watchability outputs when those runtimes are invoked.

## Kubernetes Requirements

The coordinator runs in-cluster and uses the pod service account to create and delete child resources in
`JOB_NAMESPACE`.

Required RBAC:

- pods: `create`, `get`, `list`, `delete`
- pods/log: `get`
- services: `create`, `get`, `delete`
- jobs.batch: `delete`

In hosted runs the game container can call AWS Bedrock by default, without any player opting in via `--use-bedrock`. See
[`roles/GAME.md`](../docs/roles/GAME.md#bedrock-and-aws-access).

The app backend creates the parent Job in the eval cluster. Coworld jobs use the same cluster and namespace as standard
episode jobs, but schedule onto a separate Karpenter workload lane through:

```yaml
nodeSelector:
  workload-type: coworld-jobs
tolerations:
  - key: workload-type
    operator: Equal
    value: coworld-jobs
    effect: NoSchedule
```

## Cleanup

The coordinator deletes any child player pods and the game Service in a `finally` block. Child resources also have owner
references pointing at the parent pod, so Kubernetes garbage collection can clean them up if the coordinator exits
early.

The parent Job has `ttlSecondsAfterFinished`, so completed and failed parent pods are cleaned up by the Kubernetes TTL
controller.
