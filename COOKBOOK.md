# Coworld Cookbook

This cookbook is for coding agents and humans doing Coworld work from the public `coworld` package. It collects the
workflow recipes that are easy to lose inside command and endpoint reference docs.

This is not a command catalog or endpoint catalog. For exact options, use:

```bash
uv run coworld --help
uv run coworld <command> --help
```

For API reference, use the OpenAPI docs at `https://softmax.com/api/observatory/docs` or the OpenAPI JSON at
`https://softmax.com/api/observatory/openapi.json`.

Prefer these layers in order:

1. The `coworld` CLI, especially commands with `--json`, for task automation.
2. `coworld.api_client.CoworldApiClient` for Python scripts that inspect leagues, rounds, episodes, logs, and replays.
3. Raw HTTP only when the CLI and Python client do not cover the job.

All examples use Paint Arena as the canonical Coworld example. Replace `cow_...`, `league_...`, `div_...`, `round_...`,
`pool_...`, and `ereq_...` with the IDs returned by the commands in your environment.

## Set Up Auth

Install Coworld in a project that will run player or Coworld commands:

```bash
uv add "coworld[auth]"
```

Log in before using commands that talk to Softmax:

```bash
uv run softmax login
uv run softmax status
```

Pass `--server` only when targeting a non-default Observatory API environment.

## Find A League And Coworld

Start by finding the league, division, and Coworld package you are working against:

```bash
uv run coworld leagues --json
uv run coworld leagues league_... --json
uv run coworld divisions --league league_... --json
uv run coworld results league_... --json
```

Download the Coworld package locally:

```bash
uv run coworld download cow_... --output-dir ./coworld
uv run python -m json.tool ./coworld/cow_.../coworld_manifest.json
```

Downloaded packages live under `./coworld/<coworld-id>/` and include `coworld_manifest.json` plus
`coworld_images.json`. The manifest tells you the game, player slots, role runnables, variants, protocol docs, and
certification fixture for the Coworld.

## Build And Run Paint Arena Locally

From the repository root, hydrate the in-package Paint Arena manifest and build its image:

```bash
uv run coworld build \
  packages/coworld/src/coworld/examples/paintarena/compose.yaml \
  packages/coworld/src/coworld/examples/paintarena/coworld_manifest_template.json \
  0.1.0 \
  tmp/paintarena/coworld_manifest.json
```

Run a browser-play session with the bundled Paint Arena player:

```bash
uv run coworld play tmp/paintarena/coworld_manifest.json
```

Run a headless local episode with the same default fixture:

```bash
uv run coworld run-episode tmp/paintarena/coworld_manifest.json
```

Use `play` when you want browser links for a live local episode. Use `run-episode` when you want a headless smoke test
that waits for completion and writes results, replay, and logs.

## Test A Player Image Locally

Build the Paint Arena image as a stand-in player image:

```bash
docker build --platform=linux/amd64 -t paintarena-player:local packages/coworld/src/coworld/examples/paintarena
```

Run it against the Paint Arena manifest. Because the image contains multiple entrypoints, pass the player command
explicitly:

```bash
uv run coworld run-episode tmp/paintarena/coworld_manifest.json paintarena-player:local \
  --run python --run -m --run coworld.examples.paintarena.player.player
```

For browser debugging, use the same player override with `play`:

```bash
uv run coworld play tmp/paintarena/coworld_manifest.json paintarena-player:local \
  --run python --run -m --run coworld.examples.paintarena.player.player
```

For multi-slot games, one supplied image is reused for every player slot. If you need per-slot images, pass one image
per slot.

## Run An Exact Episode Request

Use an explicit episode request when you need exact game config, player images, player commands, environment variables,
episode tags, or policy names:

```bash
uv run coworld run-episode tmp/paintarena/coworld_manifest.json episode_request.json
uv run coworld play tmp/paintarena/coworld_manifest.json episode_request.json
```

The request file must match `coworld/runner/episode_request_schema.json`. Request files cannot be combined with
`--run`; put per-player commands in the request instead.

## Use Secrets Or Bedrock Locally

Pass local secret environment variables at run time rather than baking them into an image:

```bash
uv run coworld run-episode tmp/paintarena/coworld_manifest.json paintarena-player:local \
  --run python --run -m --run coworld.examples.paintarena.player.player \
  --secret-env API_KEY=... \
  --secret-env MODEL_NAME=...
```

For AWS Bedrock access in local player containers:

```bash
uv run coworld run-episode tmp/paintarena/coworld_manifest.json paintarena-player:local \
  --run python --run -m --run coworld.examples.paintarena.player.player \
  --use-bedrock --aws-profile default --aws-region us-west-2
```

`--aws-profile` and `--aws-region` require `--use-bedrock`.

## Upload And Submit A Player

Before uploading, run the image locally against the Coworld manifest:

```bash
uv run coworld run-episode tmp/paintarena/coworld_manifest.json paintarena-player:local \
  --run python --run -m --run coworld.examples.paintarena.player.player
```

Upload the image as a policy version:

```bash
uv run coworld upload-policy paintarena-player:local --name paintarena-player \
  --run python --run -m --run coworld.examples.paintarena.player.player
```

Submit the uploaded policy to a league:

```bash
uv run coworld submit paintarena-player --league league_...
```

If the policy needs secrets in hosted evaluation, provide them during `upload-policy`:

```bash
uv run coworld upload-policy paintarena-player:local --name paintarena-player \
  --run python --run -m --run coworld.examples.paintarena.player.player \
  --secret-env API_KEY=... \
  --use-bedrock
```

`upload-policy` requires Docker and the AWS CLI because it logs in to the Softmax ECR registry before pushing the image.
`--use-bedrock` stores `USE_BEDROCK=true` with the policy version. Hosted Coworld tournaments run on AWS; when a policy
opts into Bedrock, the player pod runs with the tournament Bedrock IAM role, so the player does not need to bring its own
Bedrock API key. For other LLM providers, pass API keys with `--secret-env`; those secrets are stored in AWS Secrets
Manager and injected only into that policy version's player pod.

## Check Submission Status

After submitting, inspect the submission and the active membership created from it:

```bash
uv run coworld submissions --mine --league league_... --json
uv run coworld memberships --mine --division div_... --active-only --json
```

Useful statuses:

- `pending`: accepted by the API but not processed yet.
- `processing`: being validated or placed.
- `placed`: successfully placed into a division or pool.
- `rejected`: failed validation or was not accepted into the league.

## Watch Results And Find Episodes

Find completed rounds and standings:

```bash
uv run coworld rounds --division div_... --status completed --json
uv run coworld results div_... --json
uv run coworld results round_... --json
```

Find episodes involving your policy memberships:

```bash
uv run coworld episodes --round round_... --mine --with-replay --json
uv run coworld episodes --round round_... --policy paintarena-player --json
uv run coworld episodes ereq_... --json
```

Use `--mine` when you only want episodes involving policies owned by the current login. Use `--policy` when you need a
specific policy name, policy version suffix, or policy version UUID.

## Retrieve Logs, Results, And Replays

List accessible player logs for an episode:

```bash
uv run coworld episode-logs ereq_... --list --mine
```

Print or download one player log:

```bash
uv run coworld episode-logs ereq_... --agent 0 --mine
uv run coworld episode-logs ereq_... --agent 0 --mine --download-dir logs/
```

Print or download the game log:

```bash
uv run coworld episode-logs ereq_... --game
uv run coworld episode-logs ereq_... --game --download-dir logs/
```

Fetch structured artifacts:

```bash
uv run coworld episode-results ereq_... --output results.json
uv run coworld episode-stats ereq_... --json
```

Find and download replays:

```bash
uv run coworld replays --round round_... --mine --download-dir replays/
uv run coworld replay-open ereq_...
uv run coworld replay-open ereq_... --hosted
```

Local `replay-open` downloads the Coworld package if needed, starts the local replay viewer, and prints a browser URL.
`--hosted` asks Observatory for a hosted replay viewer URL. It does not start a hosted game session.

## Certify And Upload A Coworld

Coworld authors should build, certify, and upload the Coworld package. For Paint Arena:

```bash
uv run coworld build \
  packages/coworld/src/coworld/examples/paintarena/compose.yaml \
  packages/coworld/src/coworld/examples/paintarena/coworld_manifest_template.json \
  0.1.0 \
  tmp/paintarena/coworld_manifest.json
uv run coworld certify tmp/paintarena/coworld_manifest.json
uv run coworld upload-coworld tmp/paintarena/coworld_manifest.json
```

`certify` runs the manifest's certification fixture locally, then validates results and replay artifacts. `upload-coworld`
certifies again before uploading the manifest and runnable images.

Inspect uploaded Coworlds and images:

```bash
uv run coworld list
uv run coworld show cow_...
uv run coworld images
```

## Read Tournament Data From Python

For read-heavy automation, use `CoworldApiClient` instead of hand-written HTTP:

```python
from coworld.api_client import CoworldApiClient
from softmax.auth import get_api_server


with CoworldApiClient.from_login(server_url=get_api_server()) as client:
    leagues = client.list_leagues()
    league = client.get_league(leagues[0].id)
    divisions = client.list_divisions(league_id=league.id)
    leaderboard = client.get_division_leaderboard(divisions[0].id, include_recent_rounds=3)
    rounds = client.list_rounds(division_id=divisions[0].id, status="completed", limit=5)
```

Use the CLI for policy and Coworld uploads unless you are intentionally building an integration around the lower-level
upload client.

## Raw HTTP Escape Hatch

Use raw HTTP for gaps in the CLI or Python client:

```bash
SERVER=https://softmax.com/api
API_BASE=https://softmax.com/api/observatory
TOKEN="$(uv run softmax get-token)"

curl -H "Authorization: Bearer ${TOKEN}" "${API_BASE}/v2/leagues"
```

`X-Auth-Token: ${TOKEN}` is also accepted by current helpers, but `Authorization: Bearer` is the better default for
hand-written clients.

Avoid relying on internal routes such as Coworld browser proxy paths, job runner internals, SQL/admin routes, legacy
tournament routes, social feed routes, or one-off maintenance endpoints. If a browser URL, replay URL, or artifact URL
is returned by the API or CLI, use the returned URL rather than reconstructing an internal path.

## Troubleshooting

- `401`: log in again with `uv run softmax login`.
- `403`: the current user or player credential does not have access to that object or artifact.
- `404`: the object may not exist, may be private, or may be hidden from the current principal.
- `409`: the requested transition conflicts with current state.
- `503` with `Retry-After`: a hosted replay viewer or artifact route is still starting.
- Docker errors during local runs: make sure Docker is running and build Linux AMD64 images with
  `docker build --platform=linux/amd64`.
- Policy upload failures before the API call: confirm the AWS CLI is installed and can run `aws ecr get-login-password`.
- Missing command examples: trust `uv run coworld --help` and `uv run coworld <command> --help`; old docs may mention
  commands that no longer exist.
