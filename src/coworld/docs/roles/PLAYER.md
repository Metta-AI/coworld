# Player Role

**Status:** live

## What it does

The player role connects to the game runnable for one episode and acts in a single player slot. A player runnable
implements the game-defined player protocol: it receives observations and emits actions until the episode ends, then
exits.

Every Coworld manifest bundles one or more player runnables — typically a baseline or starter implementation useful
for certification, examples, and local play. During league episodes, the platform substitutes submitted policy
versions for the manifest's bundled players (one policy version per slot); the runtime contract is identical either
way.

## Where it lives in the manifest

`manifest.player[]`, with `type: "player"` on every entry. The array must contain at least one runnable. See
[`COWORLD_MANIFEST.md`](../COWORLD_MANIFEST.md) for the full runnable shape (`id`, `name`, `description`,
`source_url`, `image`, `run`, `env`).

## Contract

The player runnable is a short-lived container started by the episode runner once per player slot. It must:

- Read `COWORLD_PLAYER_WS_URL` from the environment. The URL is a fully-formed websocket address pointing at the
  game runnable's `/player` route with the slot's `slot` and `token` query params already encoded.
- Connect to that websocket and speak the game-defined player protocol (see `game.protocols.player` in the
  manifest). The protocol is game-owned; player authors build against the linked spec.
- Act only for the slot identified by its `COWORLD_PLAYER_WS_URL`. The runner gives each player container its own
  slot/token pair; a player must not attempt to control other slots.
- Exit cleanly when the episode ends.

Hosted runs schedule each player runnable with a 250m CPU / 256Mi memory request by default (see
[`GAME.md`](GAME.md#hosted-runtime-resources)).

Players may receive policy-scoped secret environment variables (uploaded via `coworld upload-policy --secret-env`)
on top of the manifest's public `env`. Secrets land only in the pod for the specific policy version that uploaded
them. See [`COOKBOOK.md`](../../../../COOKBOOK.md#upload-and-submit-a-player) for the policy-upload flow.

## Secrets, Bedrock, and LLM credentials

Treat `manifest.player[].env` as public configuration. Bundled players are uploaded with the Coworld package and their
images may be mirrored for user download, so neither the image nor manifest env should contain API keys, cloud
credentials, private model endpoints, or other secrets.

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

For local AWS Bedrock testing, use:

```bash
uv run coworld run-episode <manifest.json> <player-image> \
  --run python --run -m --run your_player.module \
  --use-bedrock --aws-profile default --aws-region us-west-2
```

Local `--use-bedrock` resolves host AWS credentials with the AWS CLI, sets `USE_BEDROCK=true`, and passes
`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN` when present, `AWS_REGION`, and `AWS_DEFAULT_REGION`
into the local player container. `--aws-profile` and `--aws-region` are valid only with `--use-bedrock`.

For hosted league evaluation, secrets are attached to the submitted policy version, not to the Coworld manifest:

```bash
uv run coworld upload-policy <player-image> --name <policy-name> \
  --run python --run -m --run your_player.module \
  --secret-env API_KEY=... \
  --use-bedrock
```

`upload-policy --secret-env` stores provider keys in AWS Secrets Manager and the hosted runner injects them only into
that policy version's player pod. `upload-policy --use-bedrock` stores `USE_BEDROCK=true`; hosted tournament jobs then
run that player pod with the Bedrock service account instead of requiring a Bedrock API key in the image or manifest.
For non-Bedrock LLM providers, use `--secret-env` for the provider key and keep model/provider selection in explicit
environment variables that your player code reads.

## Bundled players vs submitted policies

Player runnables reach Observatory through two distinct upload paths, and their container images have different
visibility as a result. There is no per-player flag for this — the difference is purely which upload path produced
the image.

- **Bundled players** — referenced from a Coworld's `manifest.player[]` and uploaded via `coworld upload-coworld`.
  After the upload completes, the backend's image publisher mirrors these images to ECR Public, so anyone can pull
  them as part of `coworld download <coworld-id>`. Treat their contents as fully public; do not include secrets in
  the image.
- **Submitted policies** — uploaded via `coworld upload-policy` for league submission. These images stay private to
  Observatory runtime and are never mirrored to ECR Public. Submitted policies substitute for the manifest's bundled
  players at league episode time using the same runtime contract, but their container images are not
  user-downloadable.

See [`COWORLD_MECHANICS.md`](../../../../../../app_backend/src/metta/app_backend/v2/COWORLD_MECHANICS.md) for the
container-image mirror mechanic and the distinction between Coworld-bundled images and policy upload images.

## Logging

Player runnables produce diagnostic [player logs](../artifacts/PLAYER_LOGS.md) through captured stdout/stderr and, when
available, optional `COGAME_LOG_URI` posting. Container output is diagnostic only — the source of truth for episode
success is the game's results and replay artifacts, not player logs.

The player does not receive or create an episode bundle. Its actions are represented in the
[replay artifact](../artifacts/REPLAY.md), and its container logs may be included as
[`player_logs`](../artifacts/PLAYER_LOGS.md); see [`artifacts/EPISODE_BUNDLE.md`](../artifacts/EPISODE_BUNDLE.md).

## How it fits with other roles

Players are the only role besides game that interact with the game runnable in-flight; every other role consumes the
game's output artifacts after the episode. Players' per-slot actions plus the game's tick-by-tick state become the
[replay artifact](../artifacts/REPLAY.md). See [`README.md`](../README.md) for the full artifact flow.

## See Also

- [`GAME.md`](GAME.md) — the player-side runtime contract is the mirror of the
  game runnable's `/player` websocket route.
- [`COWORLD_MANIFEST.md`](../COWORLD_MANIFEST.md) — manifest guide and generated-schema pointer.
- [`COOKBOOK.md`](../../../../COOKBOOK.md) — policy-upload flow, secrets, league submission.
- [`artifacts/EPISODE_BUNDLE.md`](../artifacts/EPISODE_BUNDLE.md) — how player-related artifacts can be bundled.
- [`artifacts/PLAYER_LOGS.md`](../artifacts/PLAYER_LOGS.md) — diagnostic logs produced by player containers.
- [`artifacts/REPLAY.md`](../artifacts/REPLAY.md) — replay artifact containing player actions and game state.
- [`README.md`](../README.md) — full artifact flow.
