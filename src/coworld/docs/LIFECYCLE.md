# Coworld Lifecycle

This page describes the lifecycle of a Coworld package and the episodes run from it. It focuses on ordering and
handoffs: what gets packaged, what runs locally, what changes in hosted tournament evaluation, which artifacts are
produced, and which roles participate at each point.

For the role model itself, see [README.md](README.md#roles). For the game container route and environment-variable
contract, see [GAME.md](roles/GAME.md). For task recipes and exact CLI commands, see the package
[COOKBOOK.md](../../../COOKBOOK.md).

## Development Loop

A Coworld exists to support a repeatable improvement loop:

1. A Coworld author packages a game, role runnables, variants, docs, schemas, and a certification fixture into a
   manifest.
2. The Coworld author certifies the package locally and uploads it when it is ready for hosted use.
3. A player author builds or selects a player image for that Coworld.
4. The player author runs local episodes, local browser-play sessions, or hosted tournament episodes.
5. The episode produces results, replay bytes, logs, and failure information when applicable.
6. Humans and coding agents inspect those outputs, improve the player or Coworld, and run the loop again.

Supporting roles such as reporter, grader, diagnoser, and optimizer consume completed episode artifacts, but they are
not part of every episode run today. See [Role Participation](#role-participation).

## Role Participation

This is the short lifecycle view of the roles. For details and status definitions, use the
[Coworld overview](README.md#roles).

| Role         | Local development                                                                | Hosted tournament evaluation                                                     |
| ------------ | -------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| Game         | Runs for `play`, `run-episode`, `certify`, and replay viewing.                   | Runs in the hosted Kubernetes episode job.                                       |
| Player       | Runs one container per slot for certification, local episodes, and browser play. | Runs one child pod per player slot, using submitted policy versions.             |
| Commissioner | `coworld certify` probes declared commissioners over `/healthz` and `/round`.    | Runs as a per-round container for leagues with `commissioner_key = "container"`. |
| Reporter     | `coworld certify` runs declared reporters against the certification episode.     | MVP hosted runner starts a per-report `/reporter` service, passes bundle URI(s), and expects a report zip at `report_uri`. |
| Grader       | Not auto-run by the local runner.                                                | Contract defined, runtime pending; consumes bundles on demand when invoked.      |
| Diagnoser    | Reserved; not run by default.                                                    | Reserved; not run by default.                                                    |
| Optimizer    | Workbench role; not an episode container.                                        | Workbench role; pulls artifacts and submits candidate policies separately.       |

Coworld does not currently provide a supported hosted game-only lobby where users connect their own remote players.
Hosted execution means tournament jobs in which the platform runs the game container and every player container.

## Package Lifecycle

A Coworld package starts with a manifest and the container images it references.

1. The author writes a `coworld_manifest.json` or manifest template.
2. The manifest declares the game, player runnables, supporting role sections, variants, game docs, protocol docs,
   schemas, and certification fixture.
3. `coworld build` can hydrate a template and build local images.
4. `coworld certify` runs the certification fixture locally as a package smoke test.
5. `coworld upload-coworld` certifies again, uploads runnable images, and publishes the manifest plus image metadata.
6. Hosted leagues and player developers can then refer to the uploaded Coworld release.

The manifest is the package map. The actual route, WebSocket, result, replay, and browser-client behavior belongs to the
game container contract in [GAME.md](roles/GAME.md).

## Certification

Coworld certification turns the manifest's `certification` fixture into one local episode. It first validates the
manifest, GitHub `source_url` resolvability, image reachability, and the certification fixture itself. It then uses the
same execution shape as a normal episode: the runner starts the game, starts the bundled player images from the fixture,
waits for the game to finish, validates final results, checks that a replay was produced, and checks that the replay
viewer can start.

Certification is a package smoke test, not a gameplay benchmark. It should be short, deterministic enough to debug, and
strong enough to prove that the manifest, game image, bundled players, HTTP routes, player-token rejection, results, and
replay surface are wired correctly.

Certification also verifies that each declared player runnable left a launch log. After the smoke episode, it runs
declared reporters against the episode bundle and validates their report zips. It probes declared commissioners with a
single `schedule_rounds_request` over `/round`, proving protocol compatibility without attempting to judge scheduling
quality. Graders and diagnosers are recorded as declared with no harness available yet; optimizers are skipped because
they belong to the later Viability degree.

## Local Development Lifecycle

Local development uses Docker on the current machine. It is the fastest loop for Coworld authors and player authors
because it writes artifacts directly to a local workspace and avoids hosted scheduling.

### Headless Local Episodes

`coworld run-episode` is the headless local execution path. Use it for smoke tests, reproducible debugging, and checking
that a player can complete one or more episodes against a manifest or explicit episode request. It runs one episode by
default; use `--episodes N` for repeated local runs.

The local runner sequence is:

1. Load the manifest or episode request.
2. Resolve the game runnable and one player runnable per slot.
3. Create a local artifact workspace.
4. Generate one token per player slot.
5. Write a concrete game config with runner-injected `tokens`.
6. Create or reuse the `coworld-local` Docker network.
7. Start the game container with `file://` config, results, and replay URIs mounted into the workspace.
8. Wait for `GET /healthz` to return 200.
9. Check the first player browser route and verify that an invalid player token is rejected.
10. Start one player container per slot with `COWORLD_PLAYER_WS_URL=ws://coworld-game-<run-id>:8080/player?...`.
11. Wait for player containers and the game container to exit.
12. Validate `results.json` against `manifest.game.results_schema`.
13. If replay verification is enabled, start the game image in replay mode and check the replay client and WebSocket.
14. Remove local game, player, and replay containers.

The local artifact workspace contains:

- `config.json`: concrete game config used for the episode, including injected tokens.
- [`results.json`](artifacts/RESULTS.md): game-written results, validated against `game.results_schema`.
- [`replay`](artifacts/REPLAY.md): exact replay bytes written by the game container.
- [`logs/game.stdout.log` and `logs/game.stderr.log`](artifacts/GAME_LOGS.md): game container stdout and stderr.
- [`logs/policy_agent_{slot}.log`](artifacts/PLAYER_LOGS.md): combined stdout and stderr for each player container.

The local runner does not upload artifacts and does not assemble an episode bundle. Bundles are assembled later, when a
consumer asks for one.

### Local Browser Play

`coworld play` uses the same local game/player contract, but it is optimized for interactive debugging:

1. Resolve the Coworld package and episode request. If given an uploaded Coworld ID and no local cache exists, it
   downloads into `./coworld/<coworld-id>/`.
2. Create a `coworld-play-*` artifact workspace.
3. Start the game container and player containers on the local Docker network.
4. Print browser URLs for player slots, the global viewer, and local admin/debug surfaces when available.
5. Keep the local session alive until the episode ends.
6. Write results, replay, and logs to the local workspace.

Use `play` when a human or agent needs live browser visibility. Use `run-episode` when the useful output is a completed
headless episode and local artifact files.

### Local Replay Viewing

Local replay viewing starts the same game image in replay mode with `COGAME_LOAD_REPLAY_URI=<file-or-http-uri>`. The
replay viewer enters through `/client/replay`, and the game's replay WebSocket streams replay data loaded from that
startup URI.

Replay mode runs the game container only. It opens the local replay viewer by default and does not start player
containers, commissioner, or supporting roles.

## Hosted Tournament Lifecycle

Hosted tournament evaluation is platform-orchestrated. Player authors upload policy images, submit them to a league, and
the platform places policy versions into tournament divisions or pools. Completed rounds and episodes then produce the
results, logs, and replays that players inspect.

Hosted episodes are created two ways: the platform schedules them as part of league rounds, or a player author requests
them directly with an Experience Request (`coworld xp-request create`), which fans out into a batch of pool-less episode
requests against a chosen Coworld or league roster. Experience-request episodes start `pending` and are dispatched
asynchronously by the platform; from dispatch onward they run the same hosted episode job described below and produce
the same artifacts. See [Cookbook: Request Experience Runs](../../../COOKBOOK.md#request-experience-runs).

This is the only supported hosted game execution path: the game and all player containers run inside platform-managed
Kubernetes jobs. For browser play while developing a Coworld or player, use local `coworld play`.

The hosted lifecycle is:

1. A Coworld release is uploaded and made available to a league.
2. A player author uploads a policy image with its run command and hosted secrets, if any.
3. The player author submits the policy to a league.
4. The platform validates or processes the submission and creates an active membership when placement succeeds.
5. The platform schedules league rounds and creates episode jobs for selected policy memberships. For container
   commissioner leagues, it starts the commissioner container and connects to `/round` so the commissioner can request
   that round's episodes.
6. Each episode job becomes a hosted Kubernetes Job.
7. The parent Job mounts an `emptyDir` workdir shared by its init, game, and worker containers.
8. The init container writes the concrete game config and generated player tokens.
9. The game container and runner worker container start.
10. The runner worker waits for the game to become healthy and creates a ClusterIP Service for player pods.
11. The runner worker creates one child player pod per slot.
12. Each player pod receives `COWORLD_PLAYER_WS_URL` and `COGAMES_ENGINE_WS_URL`, pointing at the game Service with its
    slot and token.
13. The game and players run the episode using the same game/player protocol as local execution.
14. The game writes results and replay bytes into the shared workdir.
15. The worker validates results, collects logs, and uploads the configured hosted artifacts.
16. The platform records episode status, results, logs, replay links, and round/leaderboard state. For container
    commissioner leagues, it streams completed or failed episode results back to the commissioner until
    `round_complete`, then persists commissioner rankings, membership changes, and state for the next round.
17. The coordinator deletes child player pods and the game Service; the parent Job is later removed by Kubernetes TTL
    cleanup.

Hosted output artifacts are uploaded separately rather than as one bundle:

- [`RESULTS_URI`](artifacts/RESULTS.md): game-defined `results.json`, validated against `manifest.game.results_schema`.
- [`REPLAY_URI`](artifacts/REPLAY.md): raw replay uploaded as `replay.replay`.
- [`DEBUG_URI`](artifacts/DEBUG_ARCHIVE.md): zip of runner logs, including game stdout/stderr and captured player logs.
- [`ERROR_INFO_URI`](artifacts/ERROR_INFO.md): runner failure JSON if the coordinator fails before the episode
  completes.
- [`POLICY_LOG_URLS`](artifacts/PLAYER_LOGS.md): per-slot player log destinations.
- [`PLAYER_ARTIFACT_UPLOAD_URLS`](artifacts/PLAYER_ARTIFACT.md): per-slot presigned `PUT` URLs the worker forwards into
  each player pod. The player (not the worker) uploads its own single artifact `.zip` (max 200 MB) before its pod is
  torn down.

Hosted tournament artifacts are access-controlled by the platform. CLI and API commands retrieve logs, results, stats,
and replays from those stored episode records.

## Artifact Consumption

After an episode, the runner has per-URI artifacts rather than one assembled bundle. Bundling is a consumption-time
operation. A consumer asks for a bundle when it needs one episode's artifacts as a unit, and the bundling layer
assembles the zip on demand with the requested include filters and access checks.

Grader and diagnoser runnables receive the bundle through `COGAME_EPISODE_BUNDLE_URI` when those supporting runnables
are invoked, then produce [grades](artifacts/GRADE.md) or [diagnoses](artifacts/DIAGNOSIS.md). Current in-tree reporter
examples also use that bundle-runner shape and produce [report zips](artifacts/REPORT.md), while the hosted reporter
runner starts a persisted WebSocket service that receives episode bundle URI(s) and an output `report_uri`, writes a
report zip whose contents match its purpose/output-format lane, and reports completion over `/reporter`. Optimizers
usually pull episode artifacts through Coworld tooling while operating as a longer-running workbench and produce
[optimizer outputs](artifacts/OPTIMIZER_OUTPUTS.md).

See [EPISODE_BUNDLE.md](artifacts/EPISODE_BUNDLE.md) for the bundle shape, hosted API, and planned CLI surface.

## Key Differences Between Local And Hosted

| Dimension        | Local development                                                | Hosted tournament                                                                                      |
| ---------------- | ---------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| Orchestrator     | `coworld` CLI and local Docker runner.                           | Observatory/platform plus Kubernetes runner.                                                           |
| Main use         | Fast player and Coworld debugging.                               | League evaluation and leaderboard updates.                                                             |
| Inputs           | Local manifest, downloaded Coworld, or explicit episode request. | Uploaded Coworld release, uploaded policy versions, league/division state.                             |
| Game runtime     | Docker container on `coworld-local`.                             | Game container in a parent Kubernetes Job.                                                             |
| Player runtime   | Docker containers on `coworld-local`.                            | One Kubernetes child pod per player slot.                                                              |
| Artifact storage | Local workspace files.                                           | Uploaded artifact URIs recorded by the platform.                                                       |
| Replay storage   | Exact local replay bytes.                                        | Replay bytes compressed for hosted storage and replay serving.                                         |
| Episode deadline | CLI `--timeout-seconds` for local runner waits.                  | 20 minute Kubernetes Job active deadline; coordinator waits default to `COWORLD_TIMEOUT_SECONDS=3600`. |
| Supporting roles | Not auto-run.                                                    | Commissioner is run for container leagues; reporter has an MVP hosted runner; grader runtime integration is pending. |
| Cleanup          | Local containers removed by the runner.                          | Child pods/service removed by coordinator; parent Job cleaned by TTL.                                  |

## See Also

- [README.md](README.md) for the role model and artifact flow.
- [GAME.md](roles/GAME.md) for the game container contract.
- [PLAYER.md](roles/PLAYER.md) for the player container contract.
- [RUNNER_README.md](../runner/RUNNER_README.md) for the local Docker runner.
- [KUBERNETES_RUNNER_README.md](../runner/KUBERNETES_RUNNER_README.md) for the hosted Kubernetes runner.
- [Artifact reference](artifacts/README.md) for individual artifact contracts.
- [EPISODE_BUNDLE.md](artifacts/EPISODE_BUNDLE.md) for the bundle consumed by supporting roles.
- [COOKBOOK.md](../../../COOKBOOK.md) for command recipes.
