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
`coworld_images.json`. `coworld play cow_...` starts the downloaded game and bundled player containers, prints local
player/global/admin links, and opens the global link by default; when `./coworld/<coworld-id>/coworld_manifest.json`
already exists, `play` uses that cached manifest instead of fetching it again. When the cache is missing, `play`
downloads the Coworld into that directory first.

Local browser/debug URLs printed by `coworld play`, `coworld replay`, and `coworld run-episode` use
`127.0.0.1:<port>`. Player containers do not connect back through the host; local runs attach the game and players to
Docker's private `coworld-local` network and give players a `COWORLD_PLAYER_WS_URL` under `coworld-game-<run-id>:8080`.
Linux Docker Engine users should not need UFW or `docker0` firewall changes for local Coworld episodes.

If the image needs a specific player command:

```bash
uv run coworld run-episode ./coworld/<coworld-id>/coworld_manifest.json my-runtime:latest --run python --run /app/player.py
uv run coworld upload-policy my-runtime:latest --name my-player --run python --run /app/player.py
```

`play` and `run-episode` both accept an explicit runner request:

```bash
uv run coworld run-episode ./coworld/<coworld-id>/coworld_manifest.json episode_request.json
uv run coworld play ./coworld/<coworld-id>/coworld_manifest.json episode_request.json
```

The request file must match `coworld/runner/episode_request_schema.json`. Use it when you need exact game config,
per-slot images, commands, environment variables, episode tags, or policy names. Policy names belong in the top-level
`policy_names` field, one per player slot; keep them out of `game_config` unless the game itself has a game-defined
config field for names. Without a request file, both commands use the manifest's `certification` fixture;
`play --variant <variant-id>` can instead launch a named variant. `run-episode` waits headlessly and writes artifacts.
`play` runs the same local episode path while also printing the browser/debug links. Both commands accept `--output-dir`
when you want artifacts somewhere specific.

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

## FAQ

### Which command installs or logs into Coworld?

Install Coworld into a project with `uv add "coworld[auth]"`, or install it as a tool with
`uv tool install "coworld[auth]"`. Log in with `uv run softmax login`; Coworld commands that talk to Softmax reuse that
login.

### Where does `coworld download` put files?

By default, downloaded Coworld packages go under `./coworld/<coworld-id>/`. The package includes
`coworld_manifest.json` plus `coworld_images.json`, which maps Coworld image IDs to the local or remote images the CLI
needs to run.

### When should I use `play` instead of `run-episode`?

Use `play` when you want browser links for a live local episode. Use `run-episode` when you want a headless local check
that waits for the episode to finish and writes results, replay, and logs. Both commands use the same runner request
shape, so a request file that works with one should work with the other.

### Why do I need Docker?

Local Coworld episodes run game and player images as containers. Docker must be installed and running before `play`,
`run-episode`, or image upload commands can build or run your policy image.

### Do I need the AWS CLI?

Yes for `coworld upload-policy`: it logs into the Softmax ECR registry through `aws ecr get-login-password`. Install
and configure the AWS CLI before uploading a local policy image. `coworld submit` uses the Softmax API after the policy
image has been uploaded.

### How do I tell whether my submitted policy is doing anything?

After `submit`, check `coworld submissions --mine --league league_...` for placement status. Then check
`coworld memberships --mine --division div_... --active-only` and
`coworld episodes --division div_... --mine --with-replay` to see the division membership and completed or running
episodes involving your policy.

### Where do I find logs and replays?

Use `coworld episode-logs ereq_... --list` to list available logs, then download game or per-player logs with
`--game`, `--agent <slot>`, `--mine`, or `--download-dir`. Use `coworld replay-open ereq_...` to open one replay, or
`coworld replays --division div_... --mine --download-dir replays/` to download many.

### How do I play a Coworld locally?

Download the Coworld, then run either an interactive browser session or a headless episode:

```bash
uv run coworld download <coworld-name-or-id> --output-dir ./coworld
uv run coworld play ./coworld/<coworld-id>/coworld_manifest.json
uv run coworld run-episode ./coworld/<coworld-id>/coworld_manifest.json
```

`play` prints player, global, and admin browser links and opens the global link by default. `run-episode` waits for the
episode to finish and writes artifacts without opening browser clients.

### How do I run multiple different policies locally?

Pass one image per player slot. Passing one image reuses it for every slot; passing the exact slot count assigns by
position:

```bash
uv run coworld play ./coworld/<coworld-id>/coworld_manifest.json player-a:latest player-b:latest
uv run coworld run-episode ./coworld/<coworld-id>/coworld_manifest.json player-a:latest player-b:latest
```

Use an `episode_request.json` when you need per-slot commands, env, tags, names, or exact game config:

```bash
uv run coworld play ./coworld/<coworld-id>/coworld_manifest.json episode_request.json
uv run coworld run-episode ./coworld/<coworld-id>/coworld_manifest.json episode_request.json
```

Policy display names belong in the request's top-level `policy_names` array, one name per player slot.

### How do I use Bedrock or other LLM credentials locally?

For Bedrock, pass `--use-bedrock` to `play` or `run-episode`. The CLI exports AWS credentials from the selected AWS
profile and injects them only into player containers:

```bash
uv run coworld play ./coworld/<coworld-id>/coworld_manifest.json my-player:latest \
  --use-bedrock \
  --aws-profile <aws-profile> \
  --aws-region us-west-2
```

For other providers, pass the keys as player secrets:

```bash
uv run coworld run-episode ./coworld/<coworld-id>/coworld_manifest.json my-player:latest \
  --secret-env OPENAI_API_KEY=sk-...
```

Local `--secret-env` values are process-local test inputs. Hosted policy secrets are attached when the policy is
uploaded with `coworld upload-policy --secret-env`.

### How do I pass environment variables to local players?

Use `--secret-env KEY=VALUE` for local test secrets that every local player container should receive during `play` or
`run-episode`. For per-slot local variables, put `env` on each player runnable in an `episode_request.json`. For public
defaults that are safe to publish, put the variable in the player runnable's manifest `env`.

### How do I configure game-container environment variables?

Game-container env belongs in `game.runnable.env` in the Coworld manifest. Local and hosted Coworld runtimes pass that
public env to the game container together with runner-owned variables such as `COGAME_CONFIG_URI`,
`COGAME_RESULTS_URI`, and `COGAME_SAVE_REPLAY_URI`. Bedrock and `--secret-env` are player-policy inputs, not
game-container inputs.

### How do I get local agent logs?

Local runs write per-player logs in the artifact workspace:

```text
logs/policy_agent_0.log
logs/policy_agent_1.log
```

`play`, `run-episode`, and `certify` print the artifact directory when they finish or fail.

### How do I get local game/server logs?

Local game stdout and stderr are written beside the player logs:

```text
logs/game.stdout.log
logs/game.stderr.log
```

The game-written result is `results.json`, and the game-written replay artifact is `replay` in the same workspace.

### How do I use a variant locally?

Use a manifest variant by ID:

```bash
uv run coworld play ./coworld/<coworld-id>/coworld_manifest.json --variant <variant-id>
```

For a custom local config, create an `episode_request.json` that contains the Coworld manifest, the exact `game_config`,
and the player list, then pass that request to `play` or `run-episode`.

### Is local play fast?

Local play is optimized for correctness and debugging. It starts Docker containers, waits for game health, captures
logs, and writes artifacts. Use `run-episode` for the lowest-overhead local check, keep certification fixtures small,
and use game variants with fewer players or shorter episode lengths when the game provides them.

### Can other people submit policies to my local game?

Local runs do not accept Observatory submissions. To include another person's policy in a local run, run an image your
Docker daemon can pull or build and pass it as a player image. Use `hosted-game` for shared browser play and leagues for
submitted policy evaluation.

### How do I play a hosted non-tournament game?

Create a hosted play session from an uploaded Coworld, then share the printed player command or URL:

```bash
uv run coworld hosted-game create <coworld-id>
uv run coworld hosted-game create <coworld-id> --variant <variant-id>
uv run coworld hosted-game join <play-session-id>
```

Hosted play is a browser-slot lobby. It starts the Coworld game container in Kubernetes and routes player and spectator
browser traffic through Observatory.

### Can hosted play run multiple policy containers?

Hosted play creates browser player slots, not submitted policy pods. For policy-vs-policy episodes, use a league
submission or run a local `play`/`run-episode` with the policy images or an `episode_request.json`.

### Can hosted play use Bedrock or policy secrets?

Bedrock and policy secrets are policy-container settings. Hosted play starts browser slots, not policy containers, so
there is no `--use-bedrock` or `--secret-env` path for hosted browser slots. Use policy upload plus league submission
for hosted policy containers that need Bedrock or secrets.

### Can I get hosted-play agent or server logs?

Hosted play sessions are live browser lobbies and do not create Observatory episode records. They do not expose CLI log
or replay retrieval. Use league episodes for recorded server logs, player logs, results, and replays.

### Can I use my own variant in hosted play?

Hosted play accepts variant IDs declared by the uploaded Coworld manifest:

```bash
uv run coworld hosted-game create <coworld-id> --variant <variant-id>
```

To host a new variant, publish a Coworld manifest that declares that variant, then create a hosted game from the
uploaded Coworld.

### Can I invite other users to submit policies to my hosted game?

Invite other users to join hosted play with the printed player command or player URL. Policy submission happens through
leagues:

```bash
uv run coworld upload-policy my-player:latest --name my-player
uv run coworld submit my-player --league league_...
```

### How do I submit a policy to Observatory?

Build a Linux AMD64 Docker image, run it locally, upload it, then submit the uploaded policy version to a league:

```bash
docker build --platform=linux/amd64 -t my-player:latest ./my-player
uv run coworld run-episode ./coworld/<coworld-id>/coworld_manifest.json my-player:latest
uv run coworld upload-policy my-player:latest --name my-player
uv run coworld submit my-player --league league_...
```

If the image needs a custom command, pass the same `--run` arguments to `run-episode` and `upload-policy`.

### How do I know my policy was successfully submitted?

`coworld submit` prints the submission ID and status. You can also query submissions:

```bash
uv run coworld submissions --mine --league league_...
uv run coworld submissions --policy my-player:v1 --league league_...
```

### How do I know my policy passed placement checks?

Use `submissions` and `memberships`. A submission with status `placed` has a league membership. Active memberships show
where the policy is currently competing:

```bash
uv run coworld submissions --mine --league league_...
uv run coworld memberships --mine --league league_... --active-only
```

`pending` and `processing` submissions are still waiting on placement. `rejected` submissions did not enter the league.

### How do I see how well my policy is doing?

Use league, division, and round results:

```bash
uv run coworld results league_...
uv run coworld results div_...
uv run coworld results round_...
```

Use `memberships --mine` to see your active placement and `events` to see competition updates.

### How do I see which episodes my policy has played in?

Filter episode requests by your policies or by a specific policy version:

```bash
uv run coworld episodes --division div_... --mine
uv run coworld episodes --division div_... --policy my-player:v1
uv run coworld episodes ereq_...
```

The detail view prints status, pool, Coworld ID, seed, job ID, episode ID, replay URL, participants, and scores.

### How do I retrieve a replay from an episode?

Open one replay, or download many:

```bash
uv run coworld replay-open ereq_...
uv run coworld replay-open ereq_... --hosted
uv run coworld replays --division div_... --mine --download-dir replays/
```

`replay-open` runs the game-owned replay viewer. `--hosted` creates an Observatory-hosted replay session and prints the
viewer URL.

### How do I get my policy's agent logs from an episode?

List logs for an episode, then fetch your agent logs:

```bash
uv run coworld episode-logs ereq_... --list --mine
uv run coworld episode-logs ereq_... --agent 0 --mine
uv run coworld episode-logs ereq_... --mine --download-dir logs/
```

`--mine` restricts the listed and downloaded files to agents controlled by your league memberships.

### Can I get other policies' agent logs from an episode?

Agent logs are policy-scoped. Use `--mine` for the access-scoped path; Observatory only returns logs for policy versions
you own or are allowed to inspect. Game/server logs are episode-level artifacts and are fetched separately with `--game`.

### How do I get the server logs from an episode?

Use the game log artifact:

```bash
uv run coworld episode-logs ereq_... --game
uv run coworld episode-logs ereq_... --game --download-dir logs/
```

### Can I get logs if an episode runner crashes?

Use the same `episodes` and `episode-logs` commands. Failed episode requests keep their status, job ID, and available
artifacts when the runner got far enough to create them:

```bash
uv run coworld episodes ereq_...
uv run coworld episode-logs ereq_... --game
uv run coworld episode-logs ereq_... --list --mine
```

Player logs are available for player pods that started and uploaded logs before teardown.

### How do I build an agent policy?

Read the downloaded manifest, especially `game.protocols.player` and `game.docs.pages`, then build a container that
implements the linked player protocol:

```bash
uv run coworld download <coworld-name-or-id> --output-dir ./coworld
python -m json.tool ./coworld/<coworld-id>/coworld_manifest.json | less
docker build --platform=linux/amd64 -t my-player:latest ./my-player
uv run coworld run-episode ./coworld/<coworld-id>/coworld_manifest.json my-player:latest
```

If the Coworld ships a starter template, use it as a project skeleton:

```bash
uv run coworld make-policy <starter-policy-name> -o my-player
```

### What languages can I use?

Use any language that can run inside a Linux AMD64 container and speak the game-defined websocket protocol. The fixed
runtime API is `COWORLD_PLAYER_WS_URL`: read that environment variable, connect to the websocket, receive observations,
send game-defined actions, and exit when the episode ends.

### Do I need Docker locally?

Yes for the normal build-test-upload loop. `play`, `run-episode`, and `upload-policy` operate on Docker images. Keep
Docker running locally, build images with `--platform=linux/amd64`, and run a local episode before uploading.

### Which env vars should I bake into the image?

Put public, non-secret defaults in the image or in manifest/request `env`. Do not bake API keys into the image. Attach
hosted secrets with `coworld upload-policy --secret-env KEY=VALUE`; use `--use-bedrock` for hosted Bedrock access.
During local episodes, the runner supplies `COWORLD_PLAYER_WS_URL` and any local `--secret-env` values. During hosted
league episodes, the runner supplies `COWORLD_PLAYER_WS_URL` and the secrets uploaded with that policy version.

### What contract does my policy container need to satisfy?

The container must start with its configured command, read `COWORLD_PLAYER_WS_URL`, connect to that websocket, speak the
game's player protocol, act only for that slot, and exit cleanly after the episode. Hosted runs schedule each player
with a 2 CPU / 2Gi memory baseline.

### Can I recover files my policy writes during an episode?

The portable recovery channel for player containers is stdout/stderr, available as `policy_agent_<slot>.log`. Player
container filesystems are ephemeral. Write diagnostics to stdout/stderr, or write durable artifacts to an external
store that your policy is explicitly configured to access.

## Coworld Packages

```bash
uv run coworld build path/to/compose.yaml path/to/coworld_manifest_template.json 0.1.0 build/coworld_manifest.json
uv run coworld certify path/to/coworld_manifest.json
uv run coworld upload-coworld path/to/coworld_manifest.json
uv run coworld list
uv run coworld show cow_...
uv run coworld images
uv run coworld images img_...
```

## Hosted Games

Authenticated users can host live play sessions for any uploaded Coworld and share the player and spectator links
with others.

```bash
uv run coworld hosted-game create <coworld-id>
uv run coworld hosted-game create <coworld-id> --variant <variant-id>
uv run coworld hosted-game create <coworld-id> --no-spectators
uv run coworld hosted-game join <play-session-id>
```

`hosted-game create` returns a session ID and prints:

- the player command (a `coworld hosted-game join …` line ready to copy);
- a player URL pointing at Observatory's hosted-play proxy;
- a spectator URL (when `--spectators` is on, which is the default).

`hosted-game join` claims one open player slot in an existing session and prints the player URL to open in a
browser. Each authenticated user can join a given session at most once; rejoining returns the same slot.

Hosted games are not scored league matches — they're a lightweight lobby for human play. See
[`app_backend/src/metta/app_backend/v2/COWORLD_MECHANICS.md`](../../../../app_backend/src/metta/app_backend/v2/COWORLD_MECHANICS.md)
for the backend mechanics (Kubernetes Job lifecycle, the readiness-first join flow, proxy routing).

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
uv run coworld episode-logs ereq_... --game
uv run coworld episode-logs ereq_... --agent 0
uv run coworld episode-logs ereq_... --mine --download-dir logs/
```

Hosted Coworld episode jobs collect combined stdout and stderr from the game pod and from each started player pod. The
`episode-logs` command can fetch the game log with `--game`, list per-player files, and download the per-player files
(`policy_agent_{slot}.log`).

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

## Episode Bundles

Reporters, graders, diagnosers, and optimizers consume one Coworld episode's artifacts as a single zip — an episode
bundle. The `coworld bundle` command assembles one on demand:

```bash
uv run coworld bundle ereq_... --output ep.zip
uv run coworld bundle ereq_... --output ep.zip --include results,replay,config
```

Bundles can be assembled from local runner workspaces or from hosted artifact storage; the CLI uses the same library
as the backend bundling endpoint. See [EPISODE_BUNDLE_README.md](EPISODE_BUNDLE_README.md) for the bundle contract,
the available `--include` tokens, the access-control rules, and the `COGAME_EPISODE_BUNDLE_URI` env var that
supporting runnables read.
