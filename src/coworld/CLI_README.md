# Coworld CLI

The `coworld` command uses the Observatory API and the current `softmax-cli` login. Authenticate first:

```bash
uv run softmax login
```

Pass `--server` when targeting a non-default Observatory API environment. Authentication uses the current
`softmax-cli` login.

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

Download all replay files matching a tournament scope:

```bash
uv run coworld replays --division div_... --mine --download-dir replays/
uv run coworld replays --round round_... --policy my-policy:v3 --json
```

`replays --download-dir` writes one replay JSON file per episode request plus `index.json` metadata with the episode,
job, coworld, participant, score, and source replay URI details.

Open one replay:

```bash
uv run coworld replay-open ereq_...
uv run coworld replay-open ereq_... --hosted
```

The default `replay-open` path runs the replay locally with the Coworld manifest and replay artifact. `--hosted` creates
an Observatory-hosted replay session and prints the viewer URL.
