# Coworld CLI

The `coworld` command is the public tool for Softmax v2 tournament work. It downloads Coworlds, creates starter
policies, runs local episodes, uploads game and policy containers, submits policies to leagues, and inspects results,
logs, and replays. For concepts, start with [COWORLD_README.md](COWORLD_README.md).

Commands that talk to Softmax use the current `softmax-cli` login:

```bash
uv run softmax login
```

In a project, install the CLI with:

```bash
uv init --bare --name coworld-player
uv add "coworld[auth]"
```

For one-off CLI use:

```bash
uv tool install "coworld[auth]"
```

Pass `--server` only when targeting a non-default Observatory API environment.

## Bug Reports

File Coworld bug reports as GitHub issues in the public `Metta-AI/coworld` package:

```text
https://github.com/Metta-AI/coworld/issues
```

Use that issue tracker for Coworld CLI, package, hosted runner, site-specific, and game-specific issues. Include the
command you ran, the Coworld or league name, and any relevant logs or replay links.

## Player Loop

```bash
uv run coworld download <coworld-name-or-id> --output-dir ./coworld
uv run coworld make-policy <starter-policy-name> -o my-player  # optional, when the game ships a template
docker build --platform=linux/amd64 -t my-player:latest ./my-player
uv run coworld run-episode ./coworld/<coworld-id>/coworld_manifest.json my-player:latest
uv run coworld upload-policy my-player:latest --name my-player
uv run coworld submit my-player --league league_...
```

`coworld download` stores each package under `./coworld/<coworld-id>/`, including `coworld_manifest.json` and
`coworld_images.json`. `coworld play cow_...` starts the downloaded game and bundled player containers for local
interactive play; when `./coworld/<coworld-id>/coworld_manifest.json` already exists, `play` uses that cached manifest
instead of fetching it again. When the cache is missing, `play` downloads the Coworld into that directory first.

If the image needs a specific player command:

```bash
uv run coworld run-episode ./coworld/<coworld-id>/coworld_manifest.json my-runtime:latest --run python --run /app/player.py
uv run coworld upload-policy my-runtime:latest --name my-player --run python --run /app/player.py
```

Check the submission and its first episodes:

```bash
uv run coworld submissions --mine --league league_...
uv run coworld memberships --mine --division div_... --active-only
uv run coworld episodes --division div_... --mine --with-replay
```

`make-policy` writes a game-specific starter policy when the package ships one:

```bash
uv run coworld make-policy <starter-policy-name> -o my-player
```

Use `uv run coworld make-policy --help` to list packaged templates. The copied starter policy directory is a policy
template and may include a Dockerfile. Build and test it before uploading.

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
