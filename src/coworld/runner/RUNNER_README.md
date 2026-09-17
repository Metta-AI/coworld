# Coworld Episode Runner

`coworld.runner.runner` is the local Docker runner for one Coworld episode. It always starts the game container. It
starts player containers only when `game.player_runtime` is `platform-hosted`.

The runner creates or reuses one Docker network named `coworld-local`. Game containers publish browser/debug routes on
`127.0.0.1:<port>` and also join that network as `coworld-game-<run-id>`. Player containers join the same network and
receive `COWORLD_PLAYER_WS_URL=ws://coworld-game-<run-id>:8080/player?...`.

Games can request additional host-visible TCP ports for local runs by setting `COWORLD_LOCAL_EXTRA_PORTS` in
`manifest.game.runnable.env`, using `container_port[:host_port]` entries separated by commas. For example,
`3724:3724,8085:8085` publishes container ports 3724 and 8085 on the same localhost ports, while `3724:0,8085` allocates
free host ports. The resolved mappings are passed into the game as `COWORLD_LOCAL_PORT_<container_port>` variables and
`COWORLD_LOCAL_PORTS_JSON`. This is local Docker runner behavior; the hosted Kubernetes runner does not publish
arbitrary extra host ports today.

Use it through the public CLI:

```bash
uv run coworld run-episode path/to/coworld_manifest.json my-player:latest
uv run coworld run-episode path/to/game-hosted-manifest.json path/to/player-a.py path/to/player-b.zip
```

For game-hosted mode, omit player arguments to use certification fixture files from the manifest. Explicit paths replace
the roster in slot order. The command rejects `--run`, `--secret-env`, and local Bedrock options in this mode. It reads
each file (packing a directory into a deterministic zip), records its size and SHA-256 digest in the seat, stages it
under `players/{slot}/file`, writes `player_seats.json`, and starts no player containers.

The hosted runner uses the same two paths. Platform-hosted players become child pods. Game-hosted files are staged by
the trusted init container and executed by the game.

A game may write a typed `GamePlayerFailure` to the runner-supplied `COGAME_PLAYER_FAILURE_URI` when its own rules make
a player failure terminal. The runner validates and reports it without imposing that policy on other games.

## Output Files

The local runner writes episode artifacts to its workspace directory but does not upload anywhere. The workspace
contains:

- `config.json` — concrete game config used for the episode (with runner-injected tokens)
- `results.json` — game-written results, validated against `game.results_schema`
- `replay` — game-written replay artifact (exact bytes written by the game container)
- `player_failure.json` — optional typed terminal failure written by the game to its explicit URI
- `logs/game.stdout.log`, `logs/game.stderr.log` — game container stdout/stderr
- `logs/policy_agent_{slot}.log` — combined stdout+stderr for each player container
- `player_seats.json` — game-hosted player inputs and output locations; absent in platform-hosted mode
- `players/{slot}/file` — verified game-hosted player bytes; absent in platform-hosted mode
- `policy_artifact_{slot}.zip` — optional artifact each player uploads (max 200 MiB). The runner mounts a private
  Docker-owned volume into each platform-hosted player container and sets `COWORLD_PLAYER_ARTIFACT_UPLOAD_URL` to a
  `file://` URL there. After teardown, the latest regular file is collected here, even if the episode failed. A
  game-hosted game writes the same output path from `player_seats.json`. Absent if the player uploads nothing; symlinks
  and special files are not collected. See [artifacts/PLAYER_ARTIFACT.md](../docs/artifacts/PLAYER_ARTIFACT.md).

The runner does not bundle these into a single archive — bundling is a consumption-time concern. For the canonical
per-URI output contract used by the hosted runner, see
[KUBERNETES_RUNNER_README.md](KUBERNETES_RUNNER_README.md#output-uris). For how these files get assembled into a bundle
for consumption by current one-shot graders and diagnosers, see
[artifacts/EPISODE_BUNDLE.md](../docs/artifacts/EPISODE_BUNDLE.md). Reporters do not consume bundles: they are
platform-run wasm components that read episode artifacts through the Bureau (see
[roles/REPORTER.md](../docs/roles/REPORTER.md)); the optimizer pulls artifacts through its workbench tooling.
