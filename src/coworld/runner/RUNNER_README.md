# Coworld Episode Runner

`coworld.runner.runner` is the local Docker runner for one Coworld episode. It starts the game and player containers on
the current machine, waits for the episode to finish, and writes results, replay, and logs to a local workspace.

Use it through the public CLI:

```bash
uv run coworld run-episode path/to/coworld_manifest.json my-player:latest --output-dir ./coworld-episode-results
```

The hosted production runner is `coworld.runner.kubernetes_runner`. That path uses Kubernetes containers instead of
Docker on the runner machine, but it follows the same game and player contract.
