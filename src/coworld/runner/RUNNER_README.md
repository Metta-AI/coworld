# Coworld Episode Runner

`coworld.runner.runner` is the local Docker runner for one Coworld episode. It starts the game and player containers on
the current machine, waits for the episode to finish, and writes results, replay, and logs to a local workspace.

The runner creates or reuses one Docker network named `coworld-local`. Game containers publish browser/debug routes on
`127.0.0.1:<port>` and also join that network as `coworld-game-<run-id>`. Player containers join the same network and
receive `COWORLD_PLAYER_WS_URL=ws://coworld-game-<run-id>:8080/player?...`.

Use it through the public CLI:

```bash
uv run coworld run-episode path/to/coworld_manifest.json my-player:latest
```

The hosted production runner is `coworld.runner.kubernetes_runner`. That path uses Kubernetes containers instead of
Docker on the runner machine, but it follows the same game and player contract.

## Output Files

The local runner writes episode artifacts to its workspace directory but does not upload anywhere. The workspace
contains:

- `config.json` — concrete game config used for the episode (with runner-injected tokens)
- `results.json` — game-written results, validated against `game.results_schema`
- `replay` — game-written replay artifact (exact bytes written by the game container)
- `logs/game.stdout.log`, `logs/game.stderr.log` — game container stdout/stderr
- `logs/policy_agent_{slot}.log` — combined stdout+stderr for each player container

The runner does not bundle these into a single archive — bundling is a consumption-time concern. For the canonical
per-URI output contract used by the hosted runner, see [KUBERNETES_RUNNER_README.md](KUBERNETES_RUNNER_README.md#output-uris).
For how these files get assembled into a bundle for consumption by reporters, graders, diagnosers, and optimizers,
see [EPISODE_BUNDLE_README.md](../EPISODE_BUNDLE_README.md).
