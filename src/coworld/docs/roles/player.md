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
[`MANIFEST_README.md`](../../MANIFEST_README.md) for the full runnable shape (`id`, `name`, `description`,
`source_url`, `image`, `run`, `env`).

## Contract

The player runnable is a short-lived container started by the episode runner once per player slot. It must:

- Read `COGAMES_ENGINE_WS_URL` from the environment. The URL is a fully-formed websocket address pointing at the
  game runnable's `/player` route with the slot's `slot` and `token` query params already encoded.
- Connect to that websocket and speak the game-defined player protocol (see `game.protocols.player` in the
  manifest). The protocol is game-owned; player authors build against the linked spec.
- Act only for the slot identified by its `COGAMES_ENGINE_WS_URL`. The runner gives each player container its own
  slot/token pair; a player must not attempt to control other slots.
- Exit cleanly when the episode ends.

Hosted runs schedule each player runnable with 2 CPU / 2Gi memory baseline (see
[`GAME_RUNTIME_README.md`](../../GAME_RUNTIME_README.md#hosted-runtime-resources)).

Players may receive policy-scoped secret environment variables (uploaded via `coworld upload-policy --secret-env`)
on top of the manifest's public `env`. Secrets land only in the pod for the specific policy version that uploaded
them. See [`COWORLD_README.md`](../../COWORLD_README.md) for the policy-upload flow.

## Logging

Player runnables produce diagnostic output through two independent channels:

- **stdout and stderr.** The runner captures combined stdout and stderr from every player container and writes it
  to `logs/policy_agent_{slot}.log` in the runner workspace. Hosted runs upload each player's log via
  `POLICY_LOG_URLS` and also include it inside `DEBUG_URI`'s zip. CLI consumers fetch the per-player file with
  `coworld episode-logs ereq_... --agent <slot>`, or via the bundling layer's `player_logs` include token.
- **`COGAME_LOG_URI` (optional).** When set on the player container, the player may POST newline-separated log
  lines to that URL — same posting contract as the game (see
  [`GAME_RUNTIME_README.md`](../../GAME_RUNTIME_README.md#rollout-mode)). The hosted Kubernetes runner does not set
  `COGAME_LOG_URI` on player pods by default; do not require it for correctness.

**Visibility.** Per-player logs are scoped to the policy owner by default. A non-Softmax-internal user requesting
an episode bundle with the `player_logs` include token receives only the logs for slots controlled by policy
versions they own. See [`EPISODE_BUNDLE_README.md` § Access Control](../../EPISODE_BUNDLE_README.md#access-control).

Container output is diagnostic only — the source of truth for episode success is the game's results and replay
artifacts, not player logs. Missing player logs do not fail an otherwise successful episode.

## How it fits with other roles

Players are the only role besides game that interact with the game runnable in-flight; every other role consumes
the game's output artifacts after the episode. Players' per-slot actions plus the game's tick-by-tick state become
the replay artifact that supporting runnables consume via the bundling layer. See [`OVERVIEW.md`](OVERVIEW.md) for
the full artifact flow.

## See Also

- [`GAME_RUNTIME_README.md`](../../GAME_RUNTIME_README.md) — the player-side runtime contract is the mirror of the
  game runnable's `/player` websocket route.
- [`MANIFEST_README.md`](../../MANIFEST_README.md) — manifest field reference for `manifest.player[]`.
- [`COWORLD_README.md`](../../COWORLD_README.md) — policy-upload flow, secrets, league submission.
- [`EPISODE_BUNDLE_README.md`](../../EPISODE_BUNDLE_README.md) — how player logs flow through the bundling layer.
- [`game.md`](game.md) — the runnable players connect to.
- [`OVERVIEW.md`](OVERVIEW.md) — full artifact flow.
