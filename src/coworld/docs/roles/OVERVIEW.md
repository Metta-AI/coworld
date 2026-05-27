# Coworld Roles Overview

> Canonical home for the roles system as a whole — how the seven Coworld roles compose, what artifacts move
> between them, and how the per-role docs relate.

Every Coworld is built from seven roles. Three (game, player, commissioner) participate during the episode;
four (reporter, grader, diagnoser, optimizer) consume the episode's artifacts after it ends. This document
shows how they fit together; the [per-role docs](.) describe each role's contract individually.

## Roles at a glance

| Role             | Lifecycle                  | Status                              | Doc |
| ---------------- | -------------------------- | ----------------------------------- | --- |
| **game**         | per-episode, websocket     | live                                | [`game.md`](game.md)         |
| **player**       | per-episode, websocket     | live                                | [`player.md`](player.md)     |
| **commissioner** | per-round, websocket       | contract defined, runtime pending   | [`commissioner.md`](commissioner.md) |
| **reporter**     | post-episode, on-demand    | contract defined, runtime pending   | [`reporter.md`](reporter.md) |
| **grader**       | post-episode, on-demand    | reserved (tentative contract)        | [`grader.md`](grader.md)     |
| **diagnoser**    | post-episode, on-demand    | reserved (tentative contract)        | [`diagnoser.md`](diagnoser.md) |
| **optimizer**    | workbench, long-running    | reserved (tentative contract)        | [`optimizer.md`](optimizer.md) |

See [`COWORLD_README.md` § Role Status](../../COWORLD_README.md#role-status) for the canonical definition of the
three status labels.

## Artifact flow

```text
                                  DURING EPISODE
                                  ══════════════

   ┌──────────────────┐  schedule_episodes   ┌──────────────────┐                  ┌──────────────────┐
   │   COMMISSIONER   │ ─────────────────────│       GAME       │  ◀── /player ──▶ │     PLAYERS      │
   │   per round      │                      │   per episode    │   WS  actions /  │   per slot       │
   │   /round WS      │ ◀── episode_result ──│   /healthz       │   observations   │                  │
   │                  │                      │   /player        │                  │                  │
   │ [contract        │                      │   /global        │                  │     [live]       │
   │  defined,        │                      │   /client/*      │                  │                  │
   │  runtime         │                      │                  │                  │                  │
   │  pending]        │                      │     [live]       │                  └──────────────────┘
   └──────────────────┘                      └────────┬─────────┘
                                                      │
                                                      │ writes per-URI artifacts:
                                                      │     results.json
                                                      │     replay (game-written bytes;
                                                      │              hosted upload zlib-compresses
                                                      │              at the boundary)
                                                      │     config.json
                                                      │     logs/{game,player}*.log
                                                      │     error_info.json (on failure)
                                                      ▼
   ════════════════════════════════════════════════════════════════════════════════════════════════════════

                                   POST-EPISODE
                                   ════════════

                                            ┌──────────────────┐
                                            │ bundling layer   │  ── consumers ask for what they need
                                            │ on-demand, per   │
                                            │ ereq             │
                                            │ (CLI / library / │
                                            │  backend API)    │
                                            └────────┬─────────┘
                                                     │ COGAME_EPISODE_BUNDLE_URI (.zip)
                                                     │
            ┌────────────────────────┬───────────────┴───────────────┬────────────────────────┐
            ▼                        ▼                               ▼                        ▼
   ┌──────────────┐         ┌──────────────┐               ┌──────────────────┐      ┌──────────────┐
   │   REPORTER   │         │    GRADER    │               │    DIAGNOSER     │      │   OPTIMIZER  │
   │              │         │              │               │   + target       │      │  (workbench, │
   │  [contract   │         │  [reserved]  │               │     policy URI   │      │   long-      │
   │   defined,   │         │              │               │                  │      │   running)   │
   │   runtime    │         │              │               │   [reserved]     │      │              │
   │   pending]   │         │              │               │                  │      │  [reserved]  │
   └──────┬───────┘         └──────┬───────┘               └────────┬─────────┘      └──────┬───────┘
          │                        │                                │                       │
          ▼                        ▼                                ▼                       ▼
   COGAME_REPORT_URI        COGAME_GRADE_URI                COGAME_DIAGNOSIS_URI     policy candidates,
   (.zip:                   (.json: scalar                  (.zip: assays            workspaces, evaluation
   render.md/html +         score + grader_id)              + advice)                 runs (workbench side
   event_log.parquet)                                                                  effects; final policy
                                                                                       exported via
                                                                                       coworld upload-policy)
```

## During the episode

A league round begins when the platform decides one is due. The platform spins up the **commissioner** container
for that round (see [`commissioner.md`](commissioner.md)) and connects to its `/round` WebSocket. The
commissioner reads the round context (divisions, memberships, recent results, variants, prior state blob) and
sends `schedule_episodes` listing the episodes it wants run.

For each scheduled episode, the platform's runner starts:

- One **game** container (see [`game.md`](game.md)), listening on `COGAME_HOST:COGAME_PORT` with `/healthz`,
  `/player`, `/global`, and `/client/*` routes.
- One **player** container per slot (see [`player.md`](player.md)), each receiving its own
  `COGAMES_ENGINE_WS_URL` pointing at the game's `/player` route with the slot's `slot` and `token` query
  params.

Players connect to the game's `/player` WebSocket and speak the game-defined player protocol — observations
flow from the game, actions flow from the player, until the episode ends. The game writes per-URI artifacts
(`results.json`, the game-written replay file, `config.json`, game and per-player logs, and `error_info.json`
on failure) to URIs the runner provided in env vars. Each completed episode's `scores` are routed back to the commissioner
as an `episode_result` message; the commissioner uses these to make scheduling decisions (more episodes? close
the round?) and ultimately emits `round_complete` with per-division rankings and graduation changes.

For the in-flight contract details, see [`GAME_RUNTIME_README.md`](../../GAME_RUNTIME_README.md) (the canonical
game-side runtime contract, including the browser-client behavior shared by all `/client/*` pages) and
[`commissioner.md`](commissioner.md) (the full commissioner WebSocket protocol, message payloads, and round
lifecycle).

## After the episode

Once an episode ends, the runner has produced a set of per-URI artifacts but has **not** assembled them into a
bundle — bundling is a consumption-time concern. When a consumer (a reporter run, a grader, a CLI command, a
hosted UI) wants one episode's artifacts as a unit, it asks the **bundling layer** for a bundle. The bundling
layer assembles a single `.zip` from the per-URI artifacts on demand, applying any include-filter and
access-control rules, and hands the zip back to the consumer.

See [`EPISODE_BUNDLE_README.md`](../../EPISODE_BUNDLE_README.md) for the bundling layer's full contract — the
include tokens, the inner `manifest.json` schema, the access-control rules (notably, per-user player-log
filtering), and the three surfaces (`coworld bundle` CLI, `coworld.bundle` library, `GET /v2/episodes/{ereq}/bundle`
backend API).

Supporting runnables — **reporter**, **grader**, **diagnoser** — receive an episode bundle via the
`COGAME_EPISODE_BUNDLE_URI` env var, inspect its `manifest.json` to find the files they need, run their logic,
and write a single output artifact:

- A reporter writes a `.zip` to `COGAME_REPORT_URI` with an optional `manifest.json` flagging one `render`
  target (`.md` or `.html`) and one `event_log` (parquet with `ts, player, key, value` columns; the
  structured-data surface diagnosers and optimizers consume).
- A grader writes a JSON file to `COGAME_GRADE_URI` containing a scalar `score` (plus optional `grader_id`).
- A diagnoser writes a `.zip` to `COGAME_DIAGNOSIS_URI`. Diagnosers additionally receive `COGAME_TARGET_POLICY_URI`
  identifying the policy they're evaluating against.

All three are **on-demand**, not auto-triggered by the runner. The planned CLI surfaces are `coworld run-reporter`,
`coworld run-grader`, and `coworld run-diagnoser`; exact shapes are still being settled.

The **optimizer** is the odd one out. Rather than a one-shot container that reads a bundle and writes an
artifact, an optimizer is a long-running interactive workbench (see [`optimizer.md`](optimizer.md)). It's
"opened" for a Coworld via `coworld open-optimizer`, pulls episode artifacts via the Coworld CLI as the
developer needs them, and produces side effects (policy workspaces, candidate policy versions, evaluation
runs) rather than a single output file. The canonical optimizer implementation is
[`Metta-AI/optimizers`](https://github.com/Metta-AI/optimizers).

## How the roles compose

A few composition rules that fall out of the above:

- **Three roles run during the episode** (commissioner, game, player). Of these, only **game** has a
  per-episode WebSocket contract; **commissioner** has a per-round one, and **players** connect to the game's
  WebSocket as clients rather than running servers.
- **Four roles run after the episode** (reporter, grader, diagnoser, optimizer). All four are read-only with
  respect to the episode artifacts — they consume, never modify. Three (reporter, grader, diagnoser) are
  process-style containers; the optimizer is a long-running workbench.
- **The bundling layer is the seam between in-flight and post-episode roles.** Everything before the bundling
  layer is the game's responsibility; everything after is the consumer's. The bundling layer assembles bundles
  on demand and applies access control, but stores nothing of its own.
- **`COGAME_EPISODE_BUNDLE_URI` is the canonical input env var for supporting runnables.** The corresponding
  output env vars are role-specific (`COGAME_REPORT_URI`, `COGAME_GRADE_URI`, `COGAME_DIAGNOSIS_URI`).
- **The optimizer is the only supporting role with a non-zip output shape.** Its outputs are side effects in
  its own state (candidate policies, evaluation runs); final candidate policies leave the optimizer via the
  standard `coworld upload-policy` path.

## See Also

- [`COWORLD_README.md`](../../COWORLD_README.md) — top-level Coworld guide; Role Status framework.
- [`MANIFEST_README.md`](../../MANIFEST_README.md) — field-by-field manifest reference; runnable shape; the
  `type` field per role.
- [`EPISODE_BUNDLE_README.md`](../../EPISODE_BUNDLE_README.md) — bundling-layer contract; `COGAME_EPISODE_BUNDLE_URI`.
- [`GAME_RUNTIME_README.md`](../../GAME_RUNTIME_README.md) — full game-container runtime contract; browser-client
  behavior; replay URI flow.
- [`runner/RUNNER_README.md`](../../runner/RUNNER_README.md) and
  [`runner/KUBERNETES_RUNNER_README.md`](../../runner/KUBERNETES_RUNNER_README.md) — local and hosted runners;
  per-URI output artifacts; hosted resource baseline.
- Per-role contracts: [`game.md`](game.md), [`player.md`](player.md), [`commissioner.md`](commissioner.md),
  [`reporter.md`](reporter.md), [`grader.md`](grader.md), [`diagnoser.md`](diagnoser.md), [`optimizer.md`](optimizer.md).
- Cross-repo role implementations:
  [`Metta-AI/players`](https://github.com/Metta-AI/players),
  [`Metta-AI/commissioners`](https://github.com/Metta-AI/commissioners),
  [`Metta-AI/reporters`](https://github.com/Metta-AI/reporters),
  [`Metta-AI/graders`](https://github.com/Metta-AI/graders),
  [`Metta-AI/diagnosers`](https://github.com/Metta-AI/diagnosers),
  [`Metta-AI/optimizers`](https://github.com/Metta-AI/optimizers). See
  [`docs/specs/0045-coworld-role-repos.md`](../../../../../docs/specs/0045-coworld-role-repos.md) for the
  per-repo structure and `CATALOG.yaml` schema.
