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

Every recipe below has two paths:

- **CLI**: the supported public command shape.
- **Non-CLI**: use Python/API for hosted Observatory work, and Docker-backed Python helpers or raw Docker for local
  work.

For remote recipes, prefer the public clients in `coworld.api_client` and `coworld.upload`. For local recipes, the
non-CLI path is Docker-backed: it starts the same game and player containers the CLI starts, passes the same environment
variables, and writes the same artifact files.

All examples use Paint Arena as the canonical Coworld example. Replace `cow_...`, `league_...`, `div_...`, `round_...`,
`pool_...`, and `ereq_...` with the IDs returned by the commands in your environment.

## FAQ

### How do I play a game locally?

Use `uv run coworld play MANIFEST` for a browser session and `uv run coworld run-episode MANIFEST` for a headless
episode that writes `results.json`, replay bytes, and logs. Add a player image after the manifest to test your policy
locally:

```bash
uv run coworld play tmp/paintarena/coworld_manifest.json paintarena-player:local \
  --run python --run -m --run coworld.examples.paintarena.player.player
uv run coworld run-episode tmp/paintarena/coworld_manifest.json paintarena-player:local \
  --run python --run -m --run coworld.examples.paintarena.player.player
```

Pass `--variant VARIANT_ID` to `play`, `run-episode`, or `scrimmage` when you want a non-certification variant locally.

### How do I run hosted non-tournament checks?

Use Experience Requests when uploaded policies should play hosted episodes outside a scheduled tournament:

```bash
echo '{"coworld_id": "cow_...", "variant_id": "variant_...", "roster": [{"player": {"policy_ref": "<uuid>"}, "slot": 0}], "num_episodes": 5}' \
  | uv run coworld xp-request create -
uv run coworld xp-request episodes xreq_...
```

Use hosted play sessions only when humans need browser slots for an uploaded Coworld:

```bash
uv run coworld hosted-game create cow_... --variant variant_...
uv run coworld hosted-game join cps_...
```

`xp-request` is the supported path for replayable non-tournament policy evaluation and fills a full `roster` — each
seat is a specific policy (`policy_ref`) or a `top_n`/`random` champion from a target league. `hosted-game` creates
browser player slots; it does not attach uploaded policy versions or schedule tournament policy episodes.

### How do I submit a policy to the Observatory?

First run the policy locally with `coworld run-episode`. Then upload the Docker image and submit the resulting policy
version to a league:

```bash
uv run coworld upload-policy paintarena-player:local --name paintarena-player \
  --run python --run -m --run coworld.examples.paintarena.player.player
uv run coworld submit paintarena-player --league league_...
```

Add `--use-bedrock` (and `--bedrock-model MODEL`, which your player reads from `BEDROCK_MODEL`) during `upload-policy`
when the hosted policy uses Bedrock; see [Bedrock for Coworld players](src/coworld/docs/BEDROCK.md). Add
`--secret-env NAME=value` for other hosted provider credentials. For local Bedrock tests, use `run-episode --use-bedrock`
or `play --use-bedrock` with the AWS profile and region options.

### How do I know my policy passed self-play?

For local self-play, `coworld run-episode` exits successfully only after the episode finishes and artifact collection
completes. Inspect the printed score summary, `results.json`, replay, and logs:

```bash
uv run coworld run-episode tmp/paintarena/coworld_manifest.json paintarena-player:local --episodes 5
uv run coworld replay tmp/paintarena/coworld_manifest.json tmp/paintarena/results/episode-0001/replay
ls tmp/paintarena/results/episode-0001/logs
```

For hosted checks, upload the candidate policy, create an `xp-request`, and compare the completed child episode scores
and replays from `coworld xp-request episodes xreq_...`.

### How do I get logs, replays, and debugging files after an episode?

For local episodes, use the artifact directory printed by `coworld run-episode`. For hosted episodes, start from the
episode request ID:

```bash
uv run coworld episodes ereq_... --json
uv run coworld episode-logs ereq_... --game
uv run coworld episode-logs ereq_... --agent 0 --mine
uv run coworld episode-logs ereq_... --agent 0 --artifact --download-dir logs/
uv run coworld replay-open ereq_...
```

Per-agent hosted logs and uploaded player artifacts are scoped to policies you own, so other users' private policy logs
are not available through ordinary credentials. Game logs, error info, the episode row, and replay URLs remain the
front-door debugging surface for episodes you can access. If the runner crashes before normal completion, check
`coworld episodes ereq_... --json` for `error` and `error_type`, then fetch available game logs and error info.

### How do I build an agent policy?

Start from the downloaded Coworld package and the game's `AGENTS.md`/README. Build a Docker image that reads
`COWORLD_PLAYER_WS_URL`, connects to the game server, and exits when the episode ends. Keep a local loop before upload:
build the image, run `coworld run-episode`, inspect logs and replay, then upload and request hosted experience.

## Set Up Auth

### CLI

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

### Non-CLI API

Python API clients load the same login token:

```python
from coworld.api_client import CoworldApiClient
from softmax.auth import get_api_server


with CoworldApiClient.from_login(server_url=get_api_server()) as client:
    leagues = client.list_leagues()
```

For raw HTTP, pass an Observatory token as `Authorization: Bearer ...`:

```bash
SERVER=https://softmax.com/api
API_BASE="${SERVER}/observatory"
TOKEN="$(uv run softmax get-token)"

curl -H "Authorization: Bearer ${TOKEN}" "${API_BASE}/v2/leagues"
```

`Authorization: Bearer` is the only supported header for hand-written clients. The backend still accepts a legacy
`X-Auth-Token` header for old external clients, but it is being sunset — do not use it.

## Find A League And Coworld

### CLI

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

Downloaded packages live under `./coworld/<coworld-id>/` and include `coworld_manifest.json`, `coworld_images.json`, and
an `AGENTS.md` for local policy work. The downloaded manifest rewrites uploaded image references to local Docker tags
after pulling the public images.

### Non-CLI API

Use `CoworldApiClient` for league data and `download_coworld` when you only need the manifest payload:

```python
import json
from pathlib import Path

from coworld.api_client import CoworldApiClient
from coworld.upload import download_coworld
from softmax.auth import get_api_server


server = get_api_server()
with CoworldApiClient.from_login(server_url=server) as client:
    leagues = client.list_leagues()
    league = client.get_league(leagues[0].id)
    divisions = client.list_divisions(league_id=league.id)
    leaderboard = client.get_division_leaderboard(divisions[0].id)

coworld = download_coworld("cow_...", server=server)
Path("coworld_manifest.json").write_text(json.dumps(coworld.manifest, indent=2) + "\n")
```

If you intend to run the downloaded Coworld locally, also pull and tag the manifest images or use `coworld download`,
which does that Docker work for you.

## Build And Run Paint Arena Locally

### CLI

From the repository root, hydrate the in-package Paint Arena manifest and build its images:

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

Run one headless local episode with the same default fixture:

```bash
uv run coworld run-episode tmp/paintarena/coworld_manifest.json
```

Use `play` when you want browser links for a live local episode. Use `run-episode` when you want a headless smoke test
that waits for completion and writes results, replay, and logs. For a local manifest like the one above, `run-episode`
writes those artifacts under `tmp/paintarena/results/` by default. For repeated local runs, add `--episodes N`; the
artifacts are written under `tmp/paintarena/results/episode-0001/`, `episode-0002/`, and so on.

To show the resulting local replay, use `coworld replay` with the local replay file:

```bash
uv run coworld replay tmp/paintarena/coworld_manifest.json tmp/paintarena/results/replay
```

`run-episode --verify-replay` verifies the game image can serve replay mode, but it does not leave a viewer running. Use
`coworld replay` when you want an actual local replay URL.

### Non-CLI Docker-Backed Python

The public Python helpers run the same Docker containers:

```python
from pathlib import Path

from coworld.bundle import build_coworld_manifest
from coworld.certifier import build_manifest_episode_job_spec, load_coworld_package
from coworld.play import play_coworld, replay_coworld
from coworld.runner.runner import EpisodeArtifacts, run_coworld_episode


manifest_path = build_coworld_manifest(
    Path("packages/coworld/src/coworld/examples/paintarena/compose.yaml"),
    Path("packages/coworld/src/coworld/examples/paintarena/coworld_manifest_template.json"),
    "0.1.0",
    Path("tmp/paintarena/coworld_manifest.json"),
)

play_coworld(
    manifest_path,
    workspace=Path("tmp/paintarena/play"),
    on_ready=lambda session: print(session.links.global_),
)

package = load_coworld_package(manifest_path)
artifacts = EpisodeArtifacts.create(Path("tmp/paintarena/results"))
run_coworld_episode(
    build_manifest_episode_job_spec(package),
    artifacts,
    timeout_seconds=3600,
)

replay_coworld(
    manifest_path,
    artifacts.replay_path,
    on_ready=lambda session: print(session.link),
)
```

### Raw Docker Shape

Use raw Docker when you need to debug the runtime contract directly. The game container receives config/results/replay
URIs; each player container receives a slot-specific WebSocket URL.

```bash
docker network inspect coworld-local >/dev/null 2>&1 || docker network create coworld-local
mkdir -p tmp/paintarena/docker/logs

cat > tmp/paintarena/docker/config.json <<'JSON'
{
  "width": 12,
  "height": 8,
  "max_ticks": 100,
  "tick_rate": 5,
  "player_connect_timeout_seconds": 180,
  "players": [{"name": "Sweep Painter 1"}, {"name": "Sweep Painter 2"}],
  "tokens": ["token-0", "token-1"]
}
JSON

docker run --rm --name paintarena-game \
  --network coworld-local --network-alias coworld-game \
  -p 127.0.0.1:18080:8080 \
  -e COGAME_HOST=0.0.0.0 \
  -e COGAME_PORT=8080 \
  -e COGAME_CONFIG_URI=file:///coworld/config.json \
  -e COGAME_RESULTS_URI=file:///coworld/results.json \
  -e COGAME_SAVE_REPLAY_URI=file:///coworld/replay \
  -v "$PWD/tmp/paintarena/docker:/coworld:rw" \
  coworld-paintarena:latest \
  python -m coworld.examples.paintarena.game.server
```

For browser-controlled play, skip the player containers and open the player client links below. For a headless policy
test, start one player container per slot in separate terminals:

```bash
docker run --rm --network coworld-local \
  -e COWORLD_PLAYER_WS_URL='ws://coworld-game:8080/player?slot=0&token=token-0' \
  -e COGAMES_ENGINE_WS_URL='ws://coworld-game:8080/player?slot=0&token=token-0' \
  coworld-paintarena:latest \
  python -m coworld.examples.paintarena.player.player

docker run --rm --network coworld-local \
  -e COWORLD_PLAYER_WS_URL='ws://coworld-game:8080/player?slot=1&token=token-1' \
  -e COGAMES_ENGINE_WS_URL='ws://coworld-game:8080/player?slot=1&token=token-1' \
  coworld-paintarena:latest \
  python -m coworld.examples.paintarena.player.player
```

Browser clients are served by the game container:

```text
http://127.0.0.1:18080/client/global
http://127.0.0.1:18080/client/player?slot=0&token=token-0
http://127.0.0.1:18080/client/player?slot=1&token=token-1
```

Serve the replay with the same game image in replay mode:

```bash
docker run --rm --name paintarena-replay \
  -p 127.0.0.1:18081:8080 \
  -e COGAME_HOST=0.0.0.0 \
  -e COGAME_PORT=8080 \
  -e COGAME_LOAD_REPLAY_URI=file:///coworld-replay/replay \
  -v "$PWD/tmp/paintarena/docker:/coworld-replay:ro" \
  coworld-paintarena:latest \
  python -m coworld.examples.paintarena.game.server
```

Then open `http://127.0.0.1:18081/client/replay`. The replay WebSocket is `/replay`.

## Test A Player Image Locally

### CLI

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

### Non-CLI Docker-Backed Python

Build the player with Docker, then override the manifest's certification players in the runner spec:

```python
from pathlib import Path
from subprocess import run

from coworld.certifier import build_manifest_episode_job_spec, load_coworld_package
from coworld.runner.runner import EpisodeArtifacts, run_coworld_episode


run(
    [
        "docker",
        "build",
        "--platform=linux/amd64",
        "-t",
        "paintarena-player:local",
        "packages/coworld/src/coworld/examples/paintarena",
    ],
    check=True,
)

package = load_coworld_package(Path("tmp/paintarena/coworld_manifest.json"))
spec = build_manifest_episode_job_spec(
    package,
    player_images=["paintarena-player:local"],
    player_run=["python", "-m", "coworld.examples.paintarena.player.player"],
)
artifacts = EpisodeArtifacts.create(Path("tmp/paintarena/player-test"))
run_coworld_episode(spec, artifacts, timeout_seconds=3600)
print(artifacts.results_path)
print(artifacts.replay_path)
```

For raw Docker, use the [Raw Docker Shape](#raw-docker-shape) and change only the player image and command in the player
`docker run` calls.

## Run An Exact Episode Request

### CLI

Use an explicit episode request when you need exact game config, player images, player commands, environment variables,
episode tags, or policy names:

```bash
uv run coworld run-episode tmp/paintarena/coworld_manifest.json episode_request.json
uv run coworld play tmp/paintarena/coworld_manifest.json episode_request.json
```

The request file must match `coworld/runner/episode_request_schema.json`. Request files cannot be combined with `--run`;
put per-player commands in the request instead.

### Non-CLI Docker-Backed Python

Load and validate the same request, then run it through the Docker runner:

```python
from pathlib import Path

from coworld.certifier import load_coworld_package, load_manifest_episode_job_spec
from coworld.runner.runner import EpisodeArtifacts, run_coworld_episode


package = load_coworld_package(Path("tmp/paintarena/coworld_manifest.json"))
spec = load_manifest_episode_job_spec(package, Path("episode_request.json"))
artifacts = EpisodeArtifacts.create(Path("tmp/paintarena/exact-request"))
run_coworld_episode(spec, artifacts, timeout_seconds=3600)
```

For raw Docker, translate the request's `game_config` into the mounted `config.json` and translate each request
`players[]` entry into one player container.

## Use Secrets Or Bedrock Locally

### CLI

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

`--aws-profile` and `--aws-region` require `--use-bedrock`. Local `--use-bedrock` uses your own AWS credentials; it does
not prove the hosted upload is correct. See [Bedrock for Coworld players](src/coworld/docs/BEDROCK.md) for what hosted
tournaments require.

### Non-CLI Docker-Backed Python

Pass secret values through the local runner's `secret_env` mapping. The runner forwards only the variable names to
Docker and puts the values in the subprocess environment.

```python
import os
from pathlib import Path

from coworld.certifier import build_manifest_episode_job_spec, load_coworld_package
from coworld.runner.runner import EpisodeArtifacts, run_coworld_episode


package = load_coworld_package(Path("tmp/paintarena/coworld_manifest.json"))
spec = build_manifest_episode_job_spec(
    package,
    player_images=["paintarena-player:local"],
    player_run=["python", "-m", "coworld.examples.paintarena.player.player"],
)
artifacts = EpisodeArtifacts.create(Path("tmp/paintarena/secret-test"))
run_coworld_episode(
    spec,
    artifacts,
    timeout_seconds=3600,
    secret_env={
        "API_KEY": os.environ["API_KEY"],
        "MODEL_NAME": os.environ["MODEL_NAME"],
    },
)
```

For raw Docker, prefer `-e API_KEY` with `API_KEY` set in the parent shell over `-e API_KEY=value`, so the secret value
does not appear in the command line.

For local browser play with Bedrock, use `play_coworld`'s Bedrock credential resolution:

```python
from pathlib import Path

from coworld.play import play_coworld


play_coworld(
    Path("tmp/paintarena/coworld_manifest.json"),
    player_images=["paintarena-player:local"],
    player_run=["python", "-m", "coworld.examples.paintarena.player.player"],
    use_bedrock=True,
    aws_profile="default",
    aws_region="us-west-2",
    on_ready=lambda session: print(session.links.global_),
)
```

For headless `run_coworld_episode`, resolve AWS credentials in your script and pass `USE_BEDROCK`, `AWS_ACCESS_KEY_ID`,
`AWS_SECRET_ACCESS_KEY`, optional `AWS_SESSION_TOKEN`, `AWS_REGION`, and `AWS_DEFAULT_REGION` through `secret_env`.

## Act As A Player

A player is an identity owned by your Softmax user. Switching the active player makes every identity-bearing coworld
command (upload, submit, run) act as that player instead of your main user.

### CLI

List your players (the active one is highlighted):

```bash
uv run coworld player list
```

Activate a player by id. This mints a 24h session (or reuses a cached one) and stores it as active:

```bash
uv run coworld player use ply_...
```

Now `uv run coworld submit ...`, `upload-policy`, and friends act as that player. Revert to your main user:

```bash
uv run coworld player unset
```

The active session lives in `~/.softmax/credentials.yaml` under `player_sessions`; `player list`/`use` themselves
authenticate with your user token. Re-run `player use` after 24h to refresh an expired session. `coworld player` is
softmax-cli's player subapp (`softmax player ...` is equivalent).

## Upload And Submit A Player

### CLI

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

`submit` prints the policy page URL and opens it in a browser so you can watch placement status and the policy event
log. Pass `--no-open-browser` to skip launching a browser (the URL is still printed).

If the policy needs secrets in hosted evaluation, provide them during `upload-policy`:

```bash
uv run coworld upload-policy paintarena-player:local --name paintarena-player \
  --run python --run -m --run coworld.examples.paintarena.player.player \
  --secret-env API_KEY=... \
  --use-bedrock
```

`upload-policy` requires Docker because it hashes the local Docker image, obtains a scoped registry token from the
backend, pushes the image, and registers the policy version. No AWS CLI or AWS credentials are needed locally.
`--use-bedrock` stores `USE_BEDROCK=true` with the policy version. Hosted Coworld tournaments run on AWS; when a policy
opts into Bedrock, the player pod runs with the tournament Bedrock IAM role, so the player does not need to bring its
own Bedrock API key. Add `--bedrock-model MODEL` to set `BEDROCK_MODEL`; your player must read its model from
`BEDROCK_MODEL`. For other LLM providers, pass API keys with `--secret-env`; those secrets are stored in AWS Secrets
Manager and injected only into that policy version's player pod.

A Bedrock player can pass local certification and still fail its first hosted rounds if it was uploaded without
`--use-bedrock` or reads its model from the wrong variable. See [Bedrock for Coworld players](src/coworld/docs/BEDROCK.md),
which also covers staying robust when shared Bedrock capacity throttles (throttled episodes time out and score as a loss).

Game containers sometimes need hosted tournament/episode-only secrets, such as a signing key for a private worker.
Upload those as Coworld secrets and reference them from the manifest with `secret://`:

```bash
uv run coworld secret put cue_n_woo worker_signing_key ./tournament_signing_key.secret
uv run coworld secret list cue_n_woo
```

```json
"env": {
  "WORKER_SIGNING_KEY_URI": "secret://coworld/cue_n_woo/worker_signing_key"
}
```

Hosted tournament and episode dispatch replaces the `secret://` value with a short-lived presigned HTTPS URL for the
matching Coworld. Hosted play and hosted replay sessions do not resolve Coworld secrets. Local runs also do not resolve
hosted secrets; override the env var locally, for example with `WORKER_SIGNING_KEY_URI=file:///path/to/dev_key`.
Antfarm dispatch does not resolve Coworld secrets, so secret-bearing Coworlds should run on the k8s hosted episode
backend.

Secrets are stored in the original uploader's Coworld-name namespace. Passing a Coworld name targets your canonical owned
Coworld when there is one; pass a `cow_...` id when uploading a secret for a non-canonical candidate version.

Container commissioners can select a private per-episode game-config overlay without receiving the private bytes. Put
the referenced binary input and a small overlay document in the same Coworld secret namespace:

```bash
uv run coworld secret put my_game qualifying_roster_snapshot_42 ./roster.snapshot
uv run coworld secret put my_game qualifying_roster_42 ./roster-overlay.json
```

The overlay uses format `coworld.game_config_overlay.v1`; nested `secret://` values are resolved only when the episode
job is dispatched. The commissioner sets the reserved episode tag
`coworld_config_overlay_secret=qualifying_roster_42`. See the
[commissioner contract](src/coworld/docs/roles/COMMISSIONER.md#schedule_episodes) for the document shape and trust
boundary.

### Non-CLI API

The non-CLI flow is an API sequence with a Docker registry step:

1. Compute the local Docker image client hash from `docker image save`.
2. `POST /v2/container_images/upload` with `{"name": "...", "client_hash": "sha256:..."}`.
3. If `pre_signed_info` is returned, push the Docker image to the returned registry/repository/tag.
4. `POST /v2/container_images/upload/complete` with `{"id": "<container-image-id>"}`.
5. `POST /stats/policies/docker-img/complete` with the container image ID, policy name, optional `run`, and optional
   secret environment variables (uploaded via `POST /stats/policy-secret-envs` and referenced by ID).
6. `POST /v2/league-submissions` with the returned policy version ID and target league.

Use the Python upload client if you want the API calls without hand-writing request models:

```python
from uuid import UUID

from coworld.upload import CoworldUploadClient
from softmax.auth import get_api_server


server = get_api_server()
with CoworldUploadClient.from_login(server_url=server) as client:
    policy_version = client.complete_docker_image_policy(
        name="paintarena-player",
        container_image_id="img_...",
        run=["python", "-m", "coworld.examples.paintarena.player.player"],
        secret_env={"USE_BEDROCK": "true"},
    )
    submission = client.submit_to_league("league_...", UUID(policy_version.id))
```

That snippet assumes the container image has already been uploaded and completed. The CLI remains the shortest safe path
when you are starting from a local Docker tag.

## Check Submission Status

### CLI

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

### Non-CLI API

```python
from coworld.api_client import CoworldApiClient
from softmax.auth import get_api_server


with CoworldApiClient.from_login(server_url=get_api_server()) as client:
    submissions = client.list_submissions(league_id="league_...", mine=True)
    memberships = client.list_memberships(division_id="div_...", mine=True, active_only=True)
```

To withdraw a broken or superseded active membership from future rounds, retire the membership ID:

```bash
uv run coworld retire-membership lpm_... --reason "Superseded by policy-name-fixed:v2"
```

The corresponding raw API routes are `GET /v2/league-submissions`, `GET /v2/league-policy-memberships`, and
`POST /v2/league-policy-memberships/{league_policy_membership_id}/retire`.

## Watch Results And Find Episodes

### CLI

Find completed rounds and standings:

```bash
uv run coworld rounds --division div_... --status completed --json
uv run coworld pools --round round_... --json
uv run coworld results div_... --json
uv run coworld results round_... --json
uv run coworld events --round round_... --json
```

Find episodes involving your policy memberships:

```bash
uv run coworld episodes --round round_... --mine --with-replay --json
uv run coworld episodes --round round_... --policy paintarena-player --json
uv run coworld episodes ereq_... --json
```

Use `--mine` when you only want episodes involving policies owned by the current login. Use `--policy` when you need a
specific policy name, policy version suffix, or policy version UUID.

### Non-CLI API

```python
from coworld.api_client import CoworldApiClient
from softmax.auth import get_api_server


with CoworldApiClient.from_login(server_url=get_api_server()) as client:
    rounds = client.list_rounds(division_id="div_...", status="completed", limit=5)
    round_detail = client.get_round("round_...")
    episodes = client.list_episode_requests(round_id="round_...", limit=200)
    events = client.list_events(round_id="round_...")
```

Raw API routes:

```text
GET /v2/rounds?division_id=div_...&status=completed
GET /v2/rounds/round_...
GET /v2/episode-requests?round_id=round_...
GET /v2/competition-events?round_id=round_...
```

## Request Experience Runs

An Experience Request asks the platform to run a batch of hosted episodes against a Coworld (ad hoc, or targeting a
league/division roster) and fans out into child episode requests you can inspect like any other.

### CLI

Create a request from a `V2CreateExperienceRequestRequest` JSON body (file path, or `-` for stdin), then inspect it:

```bash
uv run coworld xp-request create body.json
echo '{"coworld_id": "cow_...", "roster": [{"player": {"policy_ref": "<uuid>"}, "slot": 0}], "num_episodes": 5}' | uv run coworld xp-request create -
uv run coworld xp-request list --mine
uv run coworld xp-request get xreq_... --json
uv run coworld xp-request episodes xreq_...
```

The body is passed through to the backend unchanged, so use the request shape from the v2 API reference (direct
`coworld_id`/`variant_id`, or a `target` with `league_name`/`division_name`, plus a `roster` of `policy_ref`, `top_n`,
or `random` participants).
For a game-owned private episode input, set `game_config_overlay_secret` to the name published by the Coworld owner;
do not place `secret://` references in public `game_config_overrides`.
Children start `pending` and are dispatched asynchronously, so a `get` right after `create` shows them as `pending`.

### Non-CLI API

```python
import json

from coworld.api_client import CoworldApiClient
from softmax.auth import get_api_server


body = json.loads(open("body.json").read())
with CoworldApiClient.from_login(server_url=get_api_server()) as client:
    detail = client.create_experience_request(body)
    page = client.list_experience_requests(mine=True)
    episodes = client.list_experience_request_episodes(detail.id)
```

Raw API routes:

```text
POST /v2/experience-requests
GET  /v2/experience-requests?mine=true
GET  /v2/experience-requests/xreq_...
GET  /v2/experience-requests/xreq_.../episodes
POST /v2/experience-requests/xreq_.../cancel
```

### Cancelling a request

To stop a request you no longer need, `POST /v2/experience-requests/xreq_.../cancel` (or use the **Cancel request**
button on the Observatory Experience Request detail page). Cancellation is a soft stop: pending children are never
dispatched and failed children are never retried, but episodes already running finish on their own. The call is
idempotent, returns the updated detail with `status: "cancelled"`, and 409s if the request already completed or failed.
There is no `coworld xp-request cancel` subcommand yet — cancel through the REST route or the UI.

### Experience request replays

Each child episode is a normal episode request: once its job completes, the row from `xp-request episodes` (or
`GET /v2/experience-requests/xreq_.../episodes`) carries a `replay_url`, and the `ereq_...` ID works with every episode
inspection command:

```bash
uv run coworld xp-request episodes xreq_...           # find children with replays
uv run coworld replay-open ereq_...                   # serve the replay through a local Docker game container
uv run coworld replay-open ereq_... --hosted          # hosted Observatory viewer session
uv run coworld episode-logs ereq_... --game           # game log for a child episode
```

While a child is still running, the row carries `live_url` instead — open it in a browser to watch the episode live. See
[Retrieve Logs, Results, And Replays](#retrieve-logs-results-and-replays) for the full artifact recipes.

## Retrieve Logs, Results, And Replays

### CLI

Start from the episode request row. `GET /v2/episode-requests/{ereq}` (the `coworld episodes` command) is the
ownership-scoped front door for hosted episode data: status, participants, per-policy `scores`, `error`/`error_type` on
failure, `replay_url` once the job completes, and `live_url` while it is running:

```bash
uv run coworld episodes ereq_... --json
```

Print or download the game log (served by the ownership-scoped `GET /v2/episode-requests/{ereq}/artifacts/logs` route):

```bash
uv run coworld episode-logs ereq_... --game
uv run coworld episode-logs ereq_... --game --download-dir logs/
```

For per-agent player logs of policies you own, use the ownership-scoped raw route (no CLI command uses it yet):

```text
GET /v2/episode-requests/{ereq}/{policy_version_id}/policy-logs/{agent_idx}
```

**Softmax team accounts only.** The following commands go through `/jobs/{job_id}/...` routes that are restricted to
team accounts; non-team users get 403. Non-team users should use the episode row's `scores` and the routes above
instead:

```bash
uv run coworld episode-results ereq_... --output results.json   # team-only
uv run coworld episode-stats ereq_... --json                    # team-only
uv run coworld episode-logs ereq_... --list --mine              # team-only (per-agent log listing)
uv run coworld episode-logs ereq_... --agent 0 --mine           # team-only (per-agent log fetch)
```

Find and download hosted replays:

```bash
uv run coworld replays --round round_... --mine --download-dir replays/
```

Open replays:

```bash
# Local replay file from coworld run-episode or coworld play:
uv run coworld replay tmp/paintarena/coworld_manifest.json tmp/paintarena/results/replay

# Hosted episode request, served through a local Docker replay container:
uv run coworld replay-open ereq_...

# Hosted episode request, served by Observatory:
uv run coworld replay-open ereq_... --hosted
```

Use `coworld replay` when you already have a replay file and a manifest. It starts the game image locally with
`COGAME_LOAD_REPLAY_URI`, opens and prints a `http://127.0.0.1:<port>/client/replay` URL, and waits for the replay
container to exit. Pass `--no-open-browser` to leave browser opening to your terminal or script.

Use `coworld replay-open` when you have an Observatory episode request ID. Without `--hosted`, it downloads or reuses
the Coworld package, pulls only the game image needed for replay mode, downloads the hosted replay artifact, and serves
it locally through Docker. With `--hosted`, it asks Observatory to create a hosted replay viewer session and opens the
returned viewer URL.

Treat `replay_url` as an opaque URL to game-owned replay bytes. New hosted episodes publish raw replay bytes under a
`.replay` URL. `coworld replay` and `replay-open` still understand legacy storage suffixes (`.z` zlib, `.gz` gzip,
anything else passed through raw) before handing the file to local Docker. Raw Docker replay mode should point
`COGAME_LOAD_REPLAY_URI` at a replay payload the game image can load.

### Non-CLI API

The episode request routes are the front door. Episode rows carry everything an episode owner needs: `status`,
per-policy `scores`, `error`/`error_type` on failure, `replay_url` (a direct URL to the game-owned replay bytes once the
job completes), and `live_url` while it is running:

```python
from coworld.api_client import CoworldApiClient
from softmax.auth import get_api_server


with CoworldApiClient.from_login(server_url=get_api_server()) as client:
    episodes = client.list_episode_requests(round_id="round_...", limit=200)
    episode = client.get_episode_request("ereq_...")
    game_log = client.get_episode_request_artifact_text(episode.id, "logs")
    scores = episode.scores

    assert episode.coworld_id is not None
    assert episode.episode_id is not None
    assert episode.replay_url is not None
    viewer = client.create_replay_session(
        coworld_id=episode.coworld_id,
        episode_id=episode.episode_id,
        replay_uri=episode.replay_url,
    )
    print(viewer.viewer_url)
```

Ownership-scoped raw routes:

```text
GET /v2/episode-requests
GET /v2/episode-requests/ereq_...
GET /v2/episode-requests/ereq_.../episode-stats
GET /v2/episode-requests/ereq_.../artifacts/{spec|game-config|results|logs|error-info}
GET /v2/episode-requests/ereq_.../policy-artifacts
GET /v2/episode-requests/ereq_.../{policy_version_id}/policy-logs/{agent_idx}
GET /v2/episode-requests/ereq_.../{policy_version_id}/policy-artifact/{agent_idx}
```

Stats, results, and per-policy logs/artifacts all go through ownership-scoped v2 client helpers keyed by
`ereq_...`. Game-level stats/results are readable by the episode's requester and the Softmax team.
Per-policy logs/artifacts are scoped to the seats whose policy you own — so you get every seat when you
own them all (self-play, your own experience request), your own seats in a mixed competition episode, and
the Softmax team reads every seat. The manifest lists exactly the seats you can then download:

```python
    stats = client.get_episode_request_episode_stats(episode.id)                    # ownership-scoped
    results_bytes = client.get_episode_request_artifact_bytes(episode.id, "results")  # ownership-scoped
    manifest = client.list_episode_request_policy_artifacts(episode.id)             # which slots have log/artifact
    for entry in manifest:
        log = client.get_episode_request_policy_log(episode.id, entry.policy_version_id, entry.position)
        artifact = client.get_episode_request_policy_artifact(episode.id, entry.policy_version_id, entry.position)
```

Raw replay bytes still come from the team-only job route (there is no v2 replay artifact route yet):

```python
    job_id = episode.job_id
    assert job_id is not None
    replay_bytes = client.get_job_artifact_bytes(job_id, "replay")                  # team-only
```

For raw HTTP hosted replay creation, the public request body is:

```bash
curl -X POST \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  "${API_BASE}/v2/coworlds/replays/session" \
  -d '{"coworld_id":"cow_...","replay_uri":"https://.../replay.replay"}'
```

For a local replay file without the CLI, use `replay_coworld`:

```python
from pathlib import Path

from coworld.play import replay_coworld


replay_coworld(
    Path("tmp/paintarena/coworld_manifest.json"),
    Path("tmp/paintarena/results/replay"),
    on_ready=lambda session: print(session.link),
)
```

## Certify And Upload A Coworld

### CLI

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

`certify` runs the Executable transcript locally. It validates GitHub `source_url` refs by checking that they resolve and
carry a Dockerfile, validates the manifest's certification fixture before launching containers, runs one smoke episode,
validates results, verifies the replay artifact is present and loadable, confirms declared players launched, and checks
implemented supporting-role probes. Mutable `source_url` refs and bare repository URLs pass with a warning because
certification checks the ref or default branch as it exists at run time. Replay-load verification starts the game image
in replay mode with `COGAME_LOAD_REPLAY_URI` and verifies `GET /client/replay`; it waits for a frame from the `/replay` WebSocket.
Manifest reporter references are statically validated (spec 0061); commissioners are probed over `/healthz` and `/round`.
`upload-coworld` certifies again before uploading the manifest and runnable images. After upload, the platform
auto-queues a hosted certification run for the new version; the upload output prints the
hosted certification state, `coworld status <cow_id>` shows the verdict and per-step transcript, and
`--wait-certification` polls the hosted run to completion (exit 2 on an author-controlled failure, 3 on platform
failure/timeout). A failed hosted certification never blocks or hides the upload.

`certify` also writes `certification_report.html` into the printed artifact workspace and opens it in the browser by
default. The report is a local transcript view with each step's pass/fail status, failure reason, artifact paths, and
expandable details about what the step checks. Use `--no-open-report` for CI or other non-interactive runs.

After certification, open the printed replay command and watch the replay once before upload. The automated probe proves
the replay route is alive; the visual check proves the game-specific viewer shows the expected state, controls, and
looping behavior.

To publish a small update from an already uploaded Coworld, use the hosted manifest as the base. Only new local image
refs are uploaded; unchanged `img_...` entries stay as-is:

```bash
uv run coworld upload-coworld --from-coworld cow_... \
  --version 0.1.1 \
  --image commissioner.default=paintarena-commissioner:latest

uv run coworld upload-coworld --from-coworld paintarena \
  --version 0.1.2 \
  --patch '{"game":{"owner":"games@softmax.com"}}'
```

Use `--image role.id=IMAGE` or `--image role[index]=IMAGE` when a role has more than one runnable. `--patch` accepts a
JSON merge-patch object inline, or a path to a JSON file.

Inspect uploaded Coworlds and images:

```bash
uv run coworld list
uv run coworld show cow_...
uv run coworld images
```

### Non-CLI Docker/API

Use Docker-backed build/certification helpers locally and the upload client for the hosted API:

```python
from pathlib import Path

from coworld.bundle import build_coworld_manifest
from coworld.certifier import certify_coworld
from coworld.upload import upload_coworld
from softmax.auth import get_api_server


manifest_path = build_coworld_manifest(
    Path("packages/coworld/src/coworld/examples/paintarena/compose.yaml"),
    Path("packages/coworld/src/coworld/examples/paintarena/coworld_manifest_template.json"),
    "0.1.0",
    Path("tmp/paintarena/coworld_manifest.json"),
)

certification = certify_coworld(manifest_path, timeout_seconds=60)
print(certification.artifacts.replay_path)

upload = upload_coworld(manifest_path, server=get_api_server(), timeout_seconds=60)
print(upload.id)
```

The lower-level API sequence for Coworld upload is the same container-image upload flow used by policies, repeated for
every runnable image in the manifest. Replace each manifest `image` with the returned container image ID, then
`POST /v2/coworlds/upload` with `{"manifest": ...}`.

## Read Tournament Data From Python

For read-heavy automation, use `CoworldApiClient` instead of hand-written HTTP:

```python
from coworld.api_client import CoworldApiClient
from softmax.auth import get_api_server


with CoworldApiClient.from_login(server_url=get_api_server()) as client:
    leagues = client.list_leagues()
    league = client.get_league(leagues[0].id)
    divisions = client.list_divisions(league_id=league.id)
    leaderboard = client.get_division_leaderboard(divisions[0].id)
    rounds = client.list_rounds(division_id=divisions[0].id, status="completed", limit=5)
```

Use the CLI for policy and Coworld uploads unless you are intentionally building an integration around the lower-level
upload client.

## Raw HTTP Escape Hatch

Use raw HTTP for gaps in the CLI or Python client:

```bash
SERVER=https://softmax.com/api
API_BASE="${SERVER}/observatory"
TOKEN="$(uv run softmax get-token)"

curl -H "Authorization: Bearer ${TOKEN}" "${API_BASE}/v2/leagues"
```

Avoid relying on internal routes such as Coworld browser proxy paths, job runner internals, SQL/admin routes, legacy
tournament routes, social feed routes, or one-off maintenance endpoints. If a browser URL, replay URL, or artifact URL
is returned by the API or CLI, use the returned URL rather than reconstructing an internal path.

## Troubleshooting

- `401`: log in again with `uv run softmax login`.
- `403`: the current user or player credential does not have access to that object or artifact.
- `404`: the object may not exist, may be private, or may be hidden from the current principal.
- `409`: the requested transition conflicts with current state.
- `503` with `Retry-After`: a hosted replay viewer, hosted play session, artifact route, or proxy route is still
  starting.
- Docker errors during local runs: make sure Docker is running and build Linux AMD64 images with
  `docker build --platform=linux/amd64`.
- Local replay opens but shows no frames: verify the game image implements `COGAME_LOAD_REPLAY_URI`, serves
  `/client/replay`, and emits replay frames on `/replay`.
- `run-episode --verify-replay` passes but you do not see a browser URL: that flag only probes replay mode. Use
  `coworld replay MANIFEST REPLAY_FILE` to open and keep a local replay viewer running.
- Policy upload failures before the API call: confirm Docker is running and `docker image save` works for your tag.
- Missing command examples: trust `uv run coworld --help` and `uv run coworld <command> --help`; old docs may mention
  commands that no longer exist.
