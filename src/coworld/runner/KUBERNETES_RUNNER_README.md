# Coworld Kubernetes Runner

`coworld.runner.kubernetes_runner` is the Kubernetes entrypoint for a single Coworld episode. It replaces
Docker-in-Docker by running the game and players as ordinary Kubernetes containers.

The runner is designed to run one episode inside a single Kubernetes `Job`. That Job owns the game container and a
coordinator container. The coordinator creates one child pod for each entry in `players`, waits for the episode to
finish, gathers artifacts, then uploads them to the URIs provided in environment variables.

## Hosted resource baseline

Hosted Kubernetes runners schedule each episode component with explicit resource requests so the scheduler
reserves real capacity:

| Component                   | Resource request    |
| --------------------------- | ------------------- |
| Game container              | 1 CPU and 512Mi memory |
| Runner worker container      | 250m CPU and 256Mi memory |
| Each player container        | 250m CPU and 256Mi memory |
| Replay container             | 2 CPU and 2Gi memory |

These are scheduling **requests**, not CPU or memory limits. A container may use more if the node has spare
capacity, but game and player authors should treat the requested capacity as the portable baseline available in
hosted runs. Hosted deployments pass player requests through `COWORLD_PLAYER_CPU_REQUEST` and
`COWORLD_PLAYER_MEMORY_REQUEST`; if those env vars are omitted in a direct runner invocation, the coordinator falls back
to 2 CPU and 2Gi memory per player pod.

Per-player resource requests are configurable per job via `COWORLD_PLAYER_CPU_REQUEST` and
`COWORLD_PLAYER_MEMORY_REQUEST` (see [Optional Inputs](#optional-inputs)).

Hosted episode Jobs have a 20 minute active deadline. The coordinator's per-episode wait defaults to
`COWORLD_TIMEOUT_SECONDS=3600`; hosted dispatch currently sets the Kubernetes Job deadline to 20 minutes and gives
presigned artifact URLs one extra hour of validity.

## Parent Job Shape

The parent Job has:

- `coworld-init-config`: writes the concrete game config and player tokens into the shared workdir.
- `game`: regular non-restarting container that runs `manifest.game.runnable.image`, listens on port `8080`, and has a
  TCP liveness probe against the worker's health port (`9090`) so the kubelet stops it when the worker exits.
- `worker`: regular Job container that runs the Kubernetes coordinator and holds a TCP health port (`9090`) open for its
  whole lifetime.
- `coworld-workdir`: an `emptyDir` volume mounted into all parent containers.

The game receives URI-based artifact environment variables. Today the app backend supplies `file://` URIs inside
`COWORLD_WORKDIR` so the worker can validate results and upload hosted artifacts, but the game contract is URI-based
rather than path-based. The worker reaches the game locally for health checks and creates a ClusterIP Service so player
pods can connect back to the game. On exit — success or failure — the worker writes runner error info, collects logs,
and deletes its child player pods and Service. Because the worker holds a TCP health port open for its whole lifetime and
the game container liveness-probes that port, the kubelet stops the non-restarting game container whenever the worker
exits (timeout, crash, or OOM); the app backend deletes the parent Job. This couples the game's lifetime to the worker
without restarting the game on its own crash or exposing worker environment variables through a shared process namespace.

## Commands

```bash
python -m coworld.runner.kubernetes_runner init-config
python -m coworld.runner.kubernetes_runner run
```

`init-config` and `run` are separate commands because Kubernetes init containers must finish before the game and worker
containers start.

## Required Inputs

Both commands require:

```bash
JOB_SPEC_URI
COWORLD_WORKDIR=/coworld
```

`run` also requires:

```bash
JOB_ID
JOB_NAME
JOB_NAMESPACE
COWORLD_SERVICE_NAME
POD_NAME
POD_UID
```

`JOB_SPEC_URI` points to a JSON `CoworldEpisodeJobSpec`:

```json
{
  "manifest": {
    "game": {
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

This is the only payload shape consumed by the coordinator. Backend bookkeeping such as the uploaded Coworld ID or
manifest hash lives in the backend's stored job payload and is converted out before `spec.json` is uploaded.
Runner specs do not carry backend-owned display-name metadata. Hosted dispatch injects resolved player names only into
`game_config.players[].name`, and only when the game declares that field.

## Player Pods

The coordinator creates one pod per player:

- image: `players[].image`
- command/args: `players[].run`
- env: `players[].env`
- resource requests: 250m CPU and 256Mi memory in hosted jobs
- `COWORLD_PLAYER_WS_URL`: points at the parent game's Kubernetes Service.
- `COWORLD_PLAYER_ARTIFACT_UPLOAD_URL` (optional): a presigned `PUT` URL the player may upload a single artifact `.zip`
  (max 200 MB) to. The coordinator forwards each slot's URL from `PLAYER_ARTIFACT_UPLOAD_URLS` (see Outputs). The player
  may upload at any time but must finish before the pod is torn down after the game ends. See
  [player artifact](../docs/artifacts/PLAYER_ARTIFACT.md).

The player query string includes only the generated slot token and slot index.

The `address` query parameter is only for browser client pages served through an HTTP proxy, such as hosted play. The
Kubernetes runner does not use `address` for policy containers: `COWORLD_PLAYER_WS_URL` is the direct game websocket URL
and already includes the required `slot` and `token` query params.

## Game Container URIs

The app backend starts the game container with:

```bash
COGAME_HOST=0.0.0.0
COGAME_PORT=8080
COGAME_CONFIG_URI=file:///coworld/config.json
COGAME_RESULTS_URI=file:///coworld/results.json
COGAME_SAVE_REPLAY_URI=file:///coworld/replay
```

The game binds its HTTP and websocket server to `COGAME_HOST:COGAME_PORT`. `coworld-init-config` writes
`COGAME_CONFIG_URI` before the game starts. The game writes results and the replay to the
supplied URIs; the pod's `/coworld/replay` file holds the exact bytes the game wrote, with no runner-added extension.
The worker validates `COGAME_RESULTS_URI`, reads `/coworld/replay`, zlib-compresses those bytes in memory, and uploads
the hosted output artifacts listed below. The hosted upload artifact contract (key, content type) is unchanged; only the
in-pod workspace filename is shorter and extensionless.

## Optional Inputs

```bash
COWORLD_TIMEOUT_SECONDS=3600
COWORLD_WORKLOAD_TYPE=coworld-jobs
COWORLD_CAPACITY_TYPE=on-demand
COWORLD_PLAYER_CPU_REQUEST=250m
COWORLD_PLAYER_MEMORY_REQUEST=256Mi
LOG_LEVEL=...
```

`COWORLD_WORKLOAD_TYPE` controls the node selector and toleration applied to child player pods. In production the app
backend also applies the same workload-type selector and toleration to the parent Job.
`COWORLD_CAPACITY_TYPE` optionally adds a Karpenter capacity-type node selector, such as `on-demand`, to the parent Job
and child player pods.
`COWORLD_PLAYER_CPU_REQUEST` and `COWORLD_PLAYER_MEMORY_REQUEST` override the resource requests applied to each child
player pod. `COWORLD_TIMEOUT_SECONDS` controls coordinator waits inside the Job; the hosted parent Job also has its own
20 minute Kubernetes active deadline.

## Output URIs

The runner uploads each episode artifact to a separate URI. There is no single bundled output URI — bundling is a
consumption-time concern handled by the bundling layer; see [artifacts/EPISODE_BUNDLE.md](../docs/artifacts/EPISODE_BUNDLE.md).

All output environment variables are optional, but hosted jobs normally provide them:

```bash
RESULTS_URI
REPLAY_URI
DEBUG_URI
ERROR_INFO_URI
POLICY_LOG_URLS
PLAYER_ARTIFACT_UPLOAD_URLS
```

Outputs:

- `RESULTS_URI`: game-defined `results.json`, validated against `manifest.game.results_schema`.
- `REPLAY_URI`: zlib-compressed replay uploaded as `replay.json.z`. Hosted upload and the hosted replay viewer both
  consume the compressed form directly.
- `DEBUG_URI`: zip of the runner's `logs/` directory, containing game container stdout/stderr (`game.stdout.log`,
  `game.stderr.log`) plus any per-player log files (`policy_agent_{slot}.log`) the coordinator captured. Game
  container stdout/stderr is **public** to anyone with episode access — game authors must not write secrets or
  private information to those streams.
- `ERROR_INFO_URI`: crash JSON if the coordinator fails before the episode completes.
- `POLICY_LOG_URLS`: JSON object mapping each player slot to a destination URI. Each player log is uploaded from
  `policy_agent_{slot}.log` and contains that player container's combined stdout and stderr. Player logs are
  also included in `DEBUG_URI`'s zip; `POLICY_LOG_URLS` exposes them individually for per-player consumption.
- `PLAYER_ARTIFACT_UPLOAD_URLS`: JSON object mapping each player slot to a presigned `PUT` URL. Unlike the other
  outputs, the coordinator does **not** upload these itself — it forwards each slot's URL into the player pod as
  `COWORLD_PLAYER_ARTIFACT_UPLOAD_URL`, and the player uploads its own single artifact `.zip` (max 200 MB) before its pod
  is torn down. See [player artifact](../docs/artifacts/PLAYER_ARTIFACT.md).

Per-player logs are diagnostic only. After the game has produced valid results, the coordinator reads the last 10,000
combined stdout/stderr lines from player pods whose `player` container has started and skips pods whose container is
still waiting, such as `ContainerCreating`. Missing player logs do not fail an otherwise successful episode; result and
replay upload remain the source of truth for episode success.

There is no separate hosted media artifact for videos, screenshots, or rich human-readable reports in the episode
runner path. Put compact, replay-critical bytes in the replay artifact, keep `results.json` small and schema-valid, and
use reporter/support-role artifacts for larger watchability outputs when those runtimes are invoked.

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

The coordinator deletes child player pods and the game Service in a `finally` block. Child resources also have owner
references pointing at the parent pod, so Kubernetes garbage collection can clean them up if the coordinator exits
early.

The parent Job has `ttlSecondsAfterFinished`, so completed and failed parent pods are cleaned up by the Kubernetes TTL
controller.
