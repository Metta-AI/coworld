# Coworld CLI

The `coworld` command is the local tool for Coworld development and league work. It downloads Coworlds, runs local
episodes, uploads player images, submits policies to leagues, and inspects results. For concepts, start with
[COWORLD_README.md](COWORLD_README.md).

Commands that talk to Softmax use the current `softmax-cli` login:

```bash
uv run softmax login
```

In a standalone public environment, install the CLI with:

```bash
uv pip install "coworld[auth]"
```

Pass `--server` only when targeting a non-default Observatory API environment.

## Player Loop

```bash
uv run coworld download cow_... --output-dir ./coworld
docker build --platform=linux/amd64 -t my-player:latest .
uv run coworld run-episode ./coworld/coworld_manifest.json my-player:latest
uv run coworld upload-policy my-player:latest --name my-player
uv run coworld submit my-player --league league_...
```

If the image needs a specific player command:

```bash
uv run coworld run-episode ./coworld/coworld_manifest.json my-runtime:latest --run python --run /app/player.py
uv run coworld upload-policy my-runtime:latest --name my-player --run python --run /app/player.py
```

Check the submission and its first episodes:

```bash
uv run coworld submissions --mine --league league_...
uv run coworld memberships --mine --division div_... --active-only
uv run coworld episodes --division div_... --mine --with-replay
```

## Coworld Packages

```bash
uv run coworld certify path/to/coworld_manifest.json
uv run coworld upload-coworld path/to/coworld_manifest.json
uv run coworld list
uv run coworld show cow_...
uv run coworld images
uv run coworld images img_...
```

## Tournaments

Inspect the tournament structure:

```bash
uv run coworld leagues
uv run coworld leagues league_...
uv run coworld divisions --league league_...
uv run coworld divisions div_...
uv run coworld rounds --division div_... --status completed
uv run coworld rounds round_...
uv run coworld pools --round round_...
uv run coworld pools pool_...
```

Inspect tournament outcomes:

```bash
uv run coworld results league_...
uv run coworld results div_...
uv run coworld results round_...
uv run coworld memberships --mine --division div_... --active-only
uv run coworld submissions --mine --league league_...
uv run coworld events --division div_...
```

Most commands support `--json` for machine-readable output.

## Episodes

List episode requests by pool, round, or division:

```bash
uv run coworld episodes --division div_...
uv run coworld episodes --round round_... --with-replay
uv run coworld episodes --pool pool_... --policy my-policy:v3
uv run coworld episodes ereq_...
```

Use `--mine` to keep only episodes involving policy versions in your current league memberships:

```bash
uv run coworld episodes --division div_... --mine --with-replay --json
```

Fetch artifacts for one episode request:

```bash
uv run coworld episode-stats ereq_...
uv run coworld episode-stats ereq_... --json
uv run coworld episode-results ereq_... --output results.json
uv run coworld episode-logs ereq_... --list
uv run coworld episode-logs ereq_... --agent 0
uv run coworld episode-logs ereq_... --mine --download-dir logs/
```

Download replay files:

```bash
uv run coworld replays --division div_... --mine --download-dir replays/
uv run coworld replays --round round_... --policy my-policy:v3 --json
```

`replays --download-dir` writes one replay JSON file per episode request plus `index.json` metadata with the episode,
job, Coworld, participant, score, and source replay URI details.

Open one replay:

```bash
uv run coworld replay-open ereq_...
uv run coworld replay-open ereq_... --hosted
```

The default `replay-open` path runs the replay locally with the Coworld manifest and replay artifact. `--hosted` creates
an Observatory-hosted replay session and prints the viewer URL.
