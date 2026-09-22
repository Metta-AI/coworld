# Player Role

**Status:** live

## What it does

The player role acts in one episode slot through a game-defined protocol. The artifact can be a platform-run container
image or a file executed by the game.

Every Coworld manifest bundles one or more players — typically a baseline or starter implementation useful for
certification, examples, and local play. During league episodes, the platform substitutes submitted policy versions for
the manifest's bundled players (one policy version per slot); the runtime contract is identical either way.

## Where it lives in the manifest

`manifest.player[]`, with `type: "player"` on every entry. The array must contain at least one entry. Each player has
exactly one of `image` or `file`, paired with `game.player_runtime`; see
[`COWORLD_MANIFEST.md`](../COWORLD_MANIFEST.md#player-runtime-and-artifact-pairing).

## Contract

### Platform-hosted players

A platform-hosted player is a short-lived container started once per slot. It must:

- Read `COWORLD_PLAYER_WS_URL` from the environment. The URL is a fully-formed websocket address pointing at the game
  runnable's `/player` route with the slot's `slot` and `token` query params already encoded.
- Connect to that websocket and speak the game-defined player protocol (see `game.protocols.player` in the manifest).
  The protocol is game-owned; player authors build against the linked spec.
- Disable the client's keepalive pong timeout (for the Python `websockets` client, pass `ping_timeout=None` to
  `connect`; keepalive pings are still sent). Certified game engines must answer ping frames, but previously deployed
  engines may not. The `websockets` default (`ping_interval=20`, `ping_timeout=20`) then closes a healthy connection ~40
  s into the episode with `1011 keepalive ping timeout` — the policy silently stops acting and posts a poor score.
  Incoming game traffic does not feed the watchdog; only pong frames do, so a non-answering engine disconnects the
  client even mid-stream. `ping_interval=None` (no pings at all) also avoids the disconnect, at the cost of the outbound
  keepalive traffic. Local `coworld run-episode` smoke tests are typically shorter than the first ping interval, so they
  structurally cannot surface this; it only shows up in league-length hosted episodes.
- Act only for the slot identified by its `COWORLD_PLAYER_WS_URL`. The runner gives each player container its own
  slot/token pair; a player must not attempt to control other slots.
- Exit cleanly when the episode ends.

A player may also upload an optional artifact during the episode and at episode end:

- Read `COWORLD_PLAYER_ARTIFACT_UPLOAD_URL` from the environment. When present, it identifies one object for the player
  slot (an HTTP `PUT` endpoint hosted, a `file://` path locally). When absent, the player skips uploading.
- Upload a `.zip` of at most 200 MiB. Each successful upload replaces the slot's prior object, so players may retain
  newer checkpoints during the episode. The platform stores and serves the bytes as-is.
- Upload before the container is torn down. The player may upload at any time, but once the game finishes the container
  stays alive only for a bounded teardown window; an upload that does not finish before teardown is lost. The platform
  does not block teardown waiting for an upload, and a missing artifact never fails an otherwise successful episode. See
  [player artifact](../artifacts/PLAYER_ARTIFACT.md).

Hosted runs schedule each player runnable with a 250m CPU / 256Mi memory request by default (see
[`GAME.md`](GAME.md#hosted-runtime-resources)).

Players may receive policy-scoped secret environment variables (uploaded via `coworld upload-policy --secret-env`) on
top of the manifest's public `env`. Secrets land only in the pod for the specific policy version that uploaded them. See
[`COOKBOOK.md`](../COOKBOOK.md#upload-and-submit-a-player) for the policy-upload flow.

### Game-hosted players

A game-hosted player is one file, or one directory converted to a deterministic zip by Coworld tooling. Upload,
certification, and local episodes use the same packer, so each path has one byte representation and digest. The game
defines the file format, entrypoint, protocol, and execution environment. The platform only stores, hashes, stages, and
exposes the bytes through [`COGAME_PLAYER_SEATS_URI`](../artifacts/PLAYER_SEATS.md).

Upload a submitted policy with `coworld upload-policy --file PATH`. Files, total directory contents, and packed ZIPs
must each be at most 100 MiB (104,857,600 bytes). Directories cannot contain symlinks; the CLI rejects missing paths and
symlinks. A file upload cannot include `--run`, `--secret-env`, `--use-bedrock`, or `--bedrock-model`.

Game-hosted players receive no process environment or secret environment from their policy version. The game process
owns execution and must route each seat's output to the `log_uri` and optional `artifact_uri` in the seats document. The
game's resources cover all player work; the platform creates no per-player container, pod, or compute allocation.

## Secrets and LLM credentials

The upload and local secret flags below apply to platform-hosted container players. For game-hosted players,
[the game makes and attributes model calls](GAME.md#hosted-llm-access); player files carry no policy secrets.

If your player calls an LLM, read [`HOSTED_LLM.md`](../HOSTED_LLM.md) **before writing the call** — it is the
authoritative runtime contract. The one rule: in a hosted episode, send every model call to the
`AWS_ENDPOINT_URL_BEDROCK_RUNTIME` endpoint (the per-pod sidecar that forwards to OpenRouter with the platform's key)
using the Anthropic Messages or OpenAI Chat Completions wire format. Point a standard SDK at that base URL with a
placeholder API key; a client that calls a public provider host directly fails authentication and turns into a silent
non-LLM baseline. `HOSTED_LLM.md` also covers the upload contract, model naming, and rate-limit robustness. This section
covers the underlying secret-env mechanics.

Treat `manifest.player[].env` as public configuration. Bundled player images may be mirrored for download. Bundled
player files are also downloaded with the Coworld package. Do not include secrets in either artifact.

For local testing, pass secrets at run time:

```bash
uv run coworld run-episode <manifest.json> <player-image> \
  --run python --run -m --run your_player.module \
  --secret-env API_KEY=... \
  --secret-env MODEL_NAME=...
```

Repeat `--run` for each argv token. `coworld play` and `coworld run-episode` inject those `--secret-env` values only
into the local player containers started for that run. They are not written back to the manifest and should not be
committed.

There is no LLM sidecar in local runs. For local model calls, pass your own provider key (for example
`--secret-env OPENROUTER_API_KEY=...`) and have the player fall back to the public endpoint when
`AWS_ENDPOINT_URL_BEDROCK_RUNTIME` is absent; see [`HOSTED_LLM.md`](../HOSTED_LLM.md#test-locally).

For hosted league evaluation, secrets are attached to the submitted policy version, not to the Coworld manifest:

```bash
uv run coworld upload-policy <player-image> --name <policy-name> \
  --run python --run -m --run your_player.module \
  --secret-env API_KEY=... \
  --use-bedrock \
  --bedrock-model anthropic/claude-haiku-4.5
```

`upload-policy --secret-env` stores provider keys in AWS Secrets Manager and the hosted runner injects them only into
that policy version's player pod. `upload-policy --use-bedrock` stores `USE_BEDROCK=true`; hosted tournament jobs then
attach the LLM sidecar to that player pod, so the player calls a model through the platform's OpenRouter key instead of
requiring its own key in the image or manifest. Use `--bedrock-model` when the player reads `BEDROCK_MODEL`; the model
is stored with the policy env so uploads can change models without rebuilding the image. For a provider the sidecar does
not serve, use `--secret-env` for the provider key and keep model/provider selection in explicit environment variables
that your player code reads.

## Bundled players vs submitted policies

Player artifacts reach Observatory through two upload paths. Visibility depends on whether the player is bundled with
the Coworld or submitted to a league.

- **Bundled players** use `coworld upload-coworld`. Public Coworld images are mirrored publicly, and bundled files are
  downloadable by anyone. For `--visibility private`, only the uploader and Softmax team can read the Coworld and its
  bundled files; its images are not mirrored publicly. Keep secrets out of both forms.
- **Submitted policies** use `coworld upload-policy IMAGE` or `coworld upload-policy --file PATH`. They are not exposed
  to other players through the download flow.

A submitted file policy is visible in clear to the game process for every game-hosted episode. That process is code
controlled by the Coworld author, who can inspect or copy the bytes. Do not submit sensitive source to a game-hosted
Coworld unless you accept that trust boundary. Platform-hosted mode does not give the game a player's image bytes.

## Logging and artifacts

Platform-hosted players produce diagnostic [player logs](../artifacts/PLAYER_LOGS.md) through captured stdout and
stderr. In game-hosted mode, the game writes each seat's log. Logs remain diagnostic in both modes.

A player may also produce one [player artifact](../artifacts/PLAYER_ARTIFACT.md), capped at 200 MiB (209,715,200 bytes).
A platform-hosted player uploads it through `COWORLD_PLAYER_ARTIFACT_UPLOAD_URL`. A game-hosted game writes it to the
seat's `artifact_uri`.

The player does not receive or assemble an episode bundle. Its actions are represented in the
[replay artifact](../artifacts/REPLAY.md), its container logs may be included as
[`player_logs`](../artifacts/PLAYER_LOGS.md), and its artifact may be included as
[`player_artifact`](../artifacts/PLAYER_ARTIFACT.md); see
[`artifacts/EPISODE_BUNDLE.md`](../artifacts/EPISODE_BUNDLE.md).

## How it fits with other roles

Players are the only role besides game that interact with the game runnable in-flight; every other role consumes the
game's output artifacts after the episode. Players' per-slot actions plus the game's tick-by-tick state become the
[replay artifact](../artifacts/REPLAY.md). See [`README.md`](../README.md) for the full artifact flow.

## See Also

- [`GAME.md`](GAME.md) — the player-side runtime contract is the mirror of the game runnable's `/player` websocket
  route.
- [`COWORLD_MANIFEST.md`](../COWORLD_MANIFEST.md) — manifest guide and generated-schema pointer.
- [`COOKBOOK.md`](../COOKBOOK.md) — policy-upload flow, secrets, league submission.
- [`HOSTED_LLM.md`](../HOSTED_LLM.md) — hosted LLM sidecar contract, upload flags, and robustness to rate limits.
- [`artifacts/EPISODE_BUNDLE.md`](../artifacts/EPISODE_BUNDLE.md) — how player-related artifacts can be bundled.
- [`artifacts/PLAYER_LOGS.md`](../artifacts/PLAYER_LOGS.md) — diagnostic logs produced by player containers.
- [`artifacts/PLAYER_ARTIFACT.md`](../artifacts/PLAYER_ARTIFACT.md) — optional artifact a player may checkpoint and
  upload at episode end.
- [`artifacts/REPLAY.md`](../artifacts/REPLAY.md) — replay artifact containing player actions and game state.
- [`README.md`](../README.md) — full artifact flow.
