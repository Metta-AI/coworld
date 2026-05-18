# Coworld Episode Runner

`coworld.runner.runner` is the local Docker runner for one Coworld episode. It starts the game and player containers on
the current machine, waits for the episode to finish, and writes results, replay, and logs to a local workspace.

The runner creates or reuses one Docker network named `coworld-local`. Game containers publish browser/debug routes on
`127.0.0.1:<port>` and also join that network as `coworld-game-<run-id>`. Player containers join the same network and
receive `COGAMES_ENGINE_WS_URL=ws://coworld-game-<run-id>:8080/player?...`.

Use it through the public CLI:

```bash
uv run coworld run-episode path/to/coworld_manifest.json my-player:latest
```

The hosted production runner is `coworld.runner.kubernetes_runner`. That path uses Kubernetes containers instead of
Docker on the runner machine, but it follows the same game and player contract.
