# Coworld Kubernetes Runner

`coworld.runner.kubernetes_runner` is the Kubernetes entrypoint for a single Coworld episode. It replaces
Docker-in-Docker by running the game and players as ordinary Kubernetes containers.

The runner is designed to run one episode inside a single Kubernetes `Job`. That Job owns the game container and a
coordinator container. The coordinator creates one child pod for each entry in `players`, waits for the episode to
finish, gathers artifacts, then uploads them to the URIs provided in environment variables.

## Parent Job Shape

The parent Job has:

- `coworld-init-config`: writes the concrete game config and player tokens into the shared workdir.
- `game`: regular non-restarting container that runs `manifest.game.runnable.image` and listens on port `8080`.
- `worker`: regular Job container that runs the Kubernetes coordinator.
- `coworld-workdir`: an `emptyDir` volume mounted into all parent containers.

The game receives URI-based artifact environment variables. Today the app backend supplies `file://` URIs inside
`COWORLD_WORKDIR` so the worker can validate results and upload hosted artifacts, but the game contract is URI-based
rather than path-based. The worker reaches the game locally for health checks and creates a ClusterIP Service so player
pods can connect back to the game. If the coordinator fails before the episode completes, it writes runner error info,
deletes child player pods, then deletes the parent Kubernetes Job so Kubernetes terminates the game container without
restarting it or exposing worker environment variables through a shared process namespace.

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
  "game_config": { "map": "default" },
  "players": [
    {
      "image": "example-player:latest",
      "run": ["python", "/app/player.py"],
      "env": {}
    }
  ],
  "episode_tags": {},
  "policy_names": ["policy:v1"]
}
```

This is the only payload shape consumed by the coordinator. Backend bookkeeping such as the uploaded Coworld ID or
manifest hash lives in the backend's stored job payload and is converted out before `spec.json` is uploaded.

## Player Pods

The coordinator creates one pod per player:

- image: `players[].image`
- command/args: `players[].run`
- env: `players[].env`
- `COGAMES_ENGINE_WS_URL`: points at the parent game's Kubernetes Service.

The player query string includes only the generated slot token and slot index.

The `address` query parameter is only for browser client pages served through an HTTP proxy, such as hosted play. The
Kubernetes runner does not use `address` for policy containers: `COGAMES_ENGINE_WS_URL` is the direct game websocket URL
and already includes the required `slot` and `token` query params.

## Game Container URIs

The app backend starts the game container with:

```bash
COGAME_CONFIG_URI=file:///coworld/config.json
COGAME_RESULTS_URI=file:///coworld/results.json
COGAME_SAVE_REPLAY_URI=file:///coworld/replay.json
```

`coworld-init-config` writes `COGAME_CONFIG_URI` before the game starts. The game writes results and replay to the
supplied URIs. The worker validates `COGAME_RESULTS_URI`, compresses the replay, and uploads the hosted output artifacts
listed below.

## Optional Inputs

```bash
COWORLD_TIMEOUT_SECONDS=3600
COWORLD_WORKLOAD_TYPE=coworld-jobs
LOG_LEVEL=...
```

`COWORLD_WORKLOAD_TYPE` controls the node selector and toleration applied to child player pods. In production the app
backend also applies the same workload-type selector and toleration to the parent Job.

## Output URIs

All output environment variables are optional, but hosted jobs normally provide them:

```bash
RESULTS_URI
REPLAY_URI
DEBUG_URI
ERROR_INFO_URI
POLICY_LOG_URLS
```

Outputs:

- `RESULTS_URI`: game-defined `results.json`, validated against `manifest.game.results_schema`.
- `REPLAY_URI`: gzip-compressed replay uploaded as `replay.json.z`.
- `DEBUG_URI`: zip containing game logs and any available per-player logs.
- `ERROR_INFO_URI`: crash JSON if the coordinator fails.
- `POLICY_LOG_URLS`: JSON object mapping player position to a destination URI. Each player log is uploaded from
  `policy_agent_{position}.txt`.

Per-player logs are diagnostic only. After the game has produced valid results, the coordinator reads logs from player
pods whose `player` container has started and skips pods whose container is still waiting, such as `ContainerCreating`.
Missing player logs do not fail an otherwise successful episode; result and replay upload remain the source of truth for
episode success.

## Kubernetes Requirements

The coordinator runs in-cluster and uses the pod service account to create and delete child resources in
`JOB_NAMESPACE`.

Required RBAC:

- pods: `create`, `get`, `list`, `delete`
- pods/log: `get`
- services: `create`, `get`, `delete`
- jobs.batch: `delete`

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
