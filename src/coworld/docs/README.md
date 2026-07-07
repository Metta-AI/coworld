# Coworld

This page is the conceptual home for Coworld documentation: what a complete Coworld is, which roles it contains, how the
manifest describes those roles, and how an episode turns into artifacts that player builders can learn from.

For usage-oriented guidance, use the package [README](../../../README.md) and the [Coworld cookbook](../../../COOKBOOK.md).
For the end-to-end guide to building and testing a new Coworld, use [Authoring A Coworld](AUTHORING.md).
The package documentation uses [Paint Arena](../examples/paintarena/README.md) as its canonical example. Installable
starter templates for every role ship under `coworld/templates`.
When rebuilding an existing Coworld after the June 2026 repo consolidation, use
[Rebuilding Coworlds After The Role Repo Move](REBUILDING_COWORLDS.md).

## What Is A Complete Coworld?

A Coworld is a game-centered development loop for players. It gives a player author a stable target to improve against:
run an episode, inspect what happened, update the player, and run again.

A complete Coworld includes:

- a **game** that defines rules, state, player protocols, browser clients, results, and replays;
- one or more **players** that connect to the game and choose actions;
- supporting roles that turn completed episodes into reports, grader scores, diagnoses, or optimization inputs;
- a `coworld_manifest.json` that describes the package, its role runnables, variants, docs, schemas, and certification
  fixture;
- episode artifacts that preserve what happened and make the improvement loop repeatable.

The manifest is the map of the Coworld, not the whole idea. Most player builders should begin with the game-specific
player docs and cookbook workflows, then use the manifest when they need to inspect exact runnables, variants, protocols,
or artifact contracts.

## Roles

Every Coworld is built from seven roles. Three roles participate during episode execution; four roles consume or organize
episode artifacts after the episode ends.

| Role | Lifecycle | Status | Purpose | Details |
| ---- | --------- | ------ | ------- | ------- |
| **game** | per episode, WebSocket server | live | Runs the episode, serves browser clients, and writes result/replay artifacts. | [Game role](roles/GAME.md) |
| **player** | per episode, WebSocket client | live | Connects to the game and acts in one player slot. | [Player role](roles/PLAYER.md) |
| **commissioner** | per round, WebSocket server | live for container leagues | Schedules league-round episodes and ranks policy memberships. | [Commissioner role](roles/COMMISSIONER.md) |
| **reporter** | per run, submitted Wasm program | reporter v2 (spec 0061, landing) | Turns platform evidence into declared, typed output parts — narrative renders, event logs, machine documents — via a capability-scoped tool belt. | [Reporter role](roles/REPORTER.md) |
| **grader** | post episode, on demand | contract defined, runtime pending | Scores how useful or interesting an episode is. | [Grader role](roles/GRADER.md) |
| **diagnoser** | post episode, on demand | reserved | Evaluates a target policy and emits policy-facing advice. | [Diagnoser role](roles/DIAGNOSER.md) |
| **optimizer** | workbench, long running | reserved | Drives longer-running policy-improvement work. | [Optimizer role](roles/OPTIMIZER.md) |

## Role Status

New documents and code in this package should use these status labels consistently:

- **live**: the role has a full runtime contract that the platform exercises end to end. The contract is stable enough
  to build against.
- **live for container leagues**: legacy status for the commissioner cutover; new docs should use **live** because
  hosted commissioner scheduling is container-only.
- **MVP hosted runner**: the role has a platform-run container path for the current request protocol, but the
  API/retention/output-validation surface is still intentionally minimal.
- **contract defined, runtime pending**: the role has a written contract and may have partial or in-process
  implementations, but the platform does not yet invoke a containerized runnable for this role automatically. The schema
  may still accept an omitted or empty section until the runtime integration lands.
- **target contract documented, runtime pending**: the role has a written target contract informed by external or
  prototype implementations, but the platform integration has not shipped yet. Existing examples may still use a
  transitional contract while the target runtime is being built.
- **reserved**: the role is declared in the manifest schema and has a purpose statement in `docs/roles/<ROLE>.md`, but no
  input/output contract or platform integration exists yet. The schema may accept an omitted or empty section until the
  role has a concrete runnable contract.

## Manifest

Every Coworld package has a `coworld_manifest.json`. The manifest names the game, role runnables, variants, game-authored
docs, protocol docs, schemas, and the certification fixture used by `coworld certify` and default local episode runs.

The manifest conceptually covers all seven roles. The current schema requires the stable in-flight role sections and
keeps supporting role sections optional until product workflows need concrete runnables for them. See the
[manifest guide](COWORLD_MANIFEST.md) for the authoring semantics and
[`coworld_manifest_schema.json`](../coworld_manifest_schema.json) for the exact generated JSON Schema.

## Episode Lifecycle

The short version:

1. A Coworld author packages a game, role runnables, variants, docs, schemas, and a certification fixture into a manifest.
2. A player author builds or selects a player image for that Coworld.
3. A runner starts one game container and one player container per slot for each episode.
4. Players connect to the game's `/player` WebSocket and exchange game-defined observations and actions.
5. The episode produces per-episode artifacts: [results](artifacts/RESULTS.md), [replay bytes](artifacts/REPLAY.md),
   [logs](artifacts/GAME_LOGS.md), an optional per-player [artifact](artifacts/PLAYER_ARTIFACT.md), and
   [failure information](artifacts/ERROR_INFO.md) when applicable.
6. Supporting roles consume episode evidence through bundles, tool-belt reads, or workbench tooling and produce
   [report outputs](artifacts/REPORT.md), [grades](artifacts/GRADE.md), [diagnoses](artifacts/DIAGNOSIS.md), or
   [optimizer outputs](artifacts/OPTIMIZER_OUTPUTS.md).
7. Humans and coding agents inspect those outputs, improve the player or Coworld, and run the loop again.

The full lifecycle page is under construction: [Coworld lifecycle](LIFECYCLE.md).

## Artifact Flow

```text
+----------------------------------------------------------------------------------+
| DURING AN EPISODE                                                                |
|                                                                                  |
|  Commissioner  -- schedule episodes -->  Game  <-- obs/actions -->  Players      |
|                                           |                                      |
|                                           | writes results/replay                |
+-------------------------------------------|--------------------------------------+
                                            v
+----------------------------------------------------------------------------------+
| ARTIFACT HANDOFF                                                                 |
|                                                                                  |
|  Per-episode artifacts  -->  Bundle/download API + reporter tool-belt reads      |
|  results, replay, logs, errors                 assembled or presigned on demand  |
+-------------------------------------------|--------------------------------------+
                                            v
+----------------------------------------------------------------------------------+
| AFTER AN EPISODE                                                                 |
|                                                                                  |
|  bundles feed graders/diagnosers and user downloads; reporters read evidence     |
|  through the episodes tool and emit typed output parts plus a run trace.         |
|  +-------------+   +------------+   +----------------+   +------------------+    |
|  |  Reporter   |   |   Grader   |   |   Diagnoser    |   |    Optimizer     |    |
|  | typed parts |   |   grade    |   |   diagnosis    |   |    workbench     |    |
|  +-------------+   +------------+   +----------------+   +------------------+    |
|        ^                                  ^                                      |
|        |                                  |                                      |
|   Bureau run (Wasm)              COGAME_TARGET_POLICY_URI                        |
+----------------------------------------------------------------------------------+
```

### During The Episode

A league round begins when the platform decides one is due. The platform starts the **commissioner** container for that
round and connects to its `/round` WebSocket. The commissioner reads the round context (divisions, memberships, recent
results, variants, and prior state) and sends `schedule_episodes` listing the episodes it wants run.

For each scheduled episode, the runner starts:

- one **game** container, listening on `COGAME_HOST:COGAME_PORT` with `/healthz`, `/player`, `/global`, and `/client/*`
  routes;
- one **player** container per slot, each receiving its own `COWORLD_PLAYER_WS_URL` pointing at the game's `/player`
  route with that slot's `slot` and `token` query params. `COGAMES_ENGINE_WS_URL` is also populated for compatibility
  with older players.

Players connect to the game's `/player` WebSocket and speak the game-defined player protocol. Observations flow from the
game, actions flow from the player, and the exchange continues until the episode ends. The game writes results and replay
artifacts to the URIs provided by the runner; the runner captures logs and hosted failure information. A player may also
upload an optional [artifact](artifacts/PLAYER_ARTIFACT.md) to `COWORLD_PLAYER_ARTIFACT_UPLOAD_URL` before its container
is torn down. Each completed episode's `scores` are routed back to the commissioner as an `episode_result` message; the
commissioner can schedule more episodes or emit `round_complete` with per-division rankings and policy membership events.

For the in-flight contracts, see the [game role](roles/GAME.md), the [player role](roles/PLAYER.md), and the
[commissioner role](roles/COMMISSIONER.md). For artifact contracts, see the
[artifact reference](artifacts/README.md).

### After The Episode

Once an episode ends, the runner has produced per-URI artifacts but has not assembled them into a bundle. Bundling is a
consumption-time concern. When a consumer wants one episode's artifacts as a unit, it asks the bundling layer for a
bundle. The bundling layer assembles a `.zip` on demand, applies include-filter and access-control rules, and returns the
zip to the consumer.

See the [episode bundle reference](artifacts/EPISODE_BUNDLE.md) for the bundle shape, include tokens, inner
`manifest.json` schema, access-control rules, hosted API, and planned CLI surface.

Current grader and diagnoser runnables receive an episode bundle via `COGAME_EPISODE_BUNDLE_URI`, inspect its
`manifest.json`, run their logic, and write or create their own artifact:

- a **reporter** (v2, spec 0061) is a submitted Wasm program the platform instantiates per run; it reads episode
  evidence through its `episodes` tool and emits declared, typed [output parts](artifacts/REPORT.md) — optionally
  including an [event log](artifacts/EVENT_LOG.md) part — while the host records a [run trace](artifacts/TRACE.md);
- a **grader** writes a [grade](artifacts/GRADE.md) to `COGAME_GRADE_URI`;
- a **diagnoser** writes a [diagnosis](artifacts/DIAGNOSIS.md) to `COGAME_DIAGNOSIS_URI` and also receives
  `COGAME_TARGET_POLICY_URI` identifying the policy it is evaluating;
- an **optimizer** is a long-running interactive workbench that pulls episode artifacts through Coworld tooling and
  produces [optimizer outputs](artifacts/OPTIMIZER_OUTPUTS.md) such as candidate policies, policy workspaces, and
  evaluation runs.

Grader and diagnoser runs are on-demand, not auto-triggered by the runner. The planned CLI surfaces are
`coworld run-grader` and `coworld run-diagnoser`; exact shapes are still being settled. Reporter runs are created only
by explicit bindings (on-demand requests, experience-request attachment, subscriptions) — never by episode execution
itself.

## Role Boundaries

These boundaries are useful when deciding where a new feature, artifact, or debugging hook belongs:

- **In-flight roles are different from post-episode roles.** Commissioner, game, and player run during the episode.
  Reporter, grader, diagnoser, and optimizer consume completed episode artifacts.
- **The game owns episode truth.** The game exposes the per-episode WebSocket server, receives player actions, advances
  state, and writes the raw episode artifacts.
- **Players are clients, not episode orchestrators.** A player connects to the game's `/player` WebSocket for one slot
  and does not modify the game-owned episode artifacts. It may upload its own optional
  [artifact](artifacts/PLAYER_ARTIFACT.md), but it does not own episode truth.
- **Bundle and reporter handoffs are consumption-time views.** Everything before handoff is game and runner output.
  User downloads, graders, and diagnosers use bundle zips; reporters read through their `episodes` tool with the same
  access-control rules (enforced under the run requester's permissions).
- **Supporting runnables do not all share one input shape.** Graders and diagnosers currently consume
  `COGAME_EPISODE_BUNDLE_URI`. Reporters (v2, spec 0061) are Wasm programs whose only inputs are the run request and
  the tool belt.
- **The optimizer is a workbench, not a one-shot artifact writer.** Final candidate policies leave an optimizer through
  the standard `coworld upload-policy` path.

## See Also

- Package usage and starting guide: [README](../../../README.md).
- End-to-end Coworld authoring guide: [AUTHORING.md](AUTHORING.md).
- Workflow recipes: [Coworld cookbook](../../../COOKBOOK.md).
- Rebuild/source ownership guide: [REBUILDING_COWORLDS.md](REBUILDING_COWORLDS.md).
- Manifest reference: [COWORLD_MANIFEST.md](COWORLD_MANIFEST.md).
- Calling an LLM / Bedrock from a player (route through the `AWS_ENDPOINT_URL_BEDROCK_RUNTIME` sidecar, InvokeModel not Converse): [BEDROCK.md](BEDROCK.md).
- Lifecycle overview: [LIFECYCLE.md](LIFECYCLE.md).
- Artifact reference: [artifacts/README.md](artifacts/README.md).
- Game container contract: [GAME.md](roles/GAME.md).
- Episode bundle contract: [artifacts/EPISODE_BUNDLE.md](artifacts/EPISODE_BUNDLE.md).
- Local and hosted runners: [RUNNER_README.md](../runner/RUNNER_README.md) and
  [KUBERNETES_RUNNER_README.md](../runner/KUBERNETES_RUNNER_README.md).
- Per-role contracts: [GAME.md](roles/GAME.md), [PLAYER.md](roles/PLAYER.md), [COMMISSIONER.md](roles/COMMISSIONER.md),
  [REPORTER.md](roles/REPORTER.md), [GRADER.md](roles/GRADER.md), [DIAGNOSER.md](roles/DIAGNOSER.md),
  [OPTIMIZER.md](roles/OPTIMIZER.md).
- Shared role implementations: [Metta-AI/coworld-tools](https://github.com/Metta-AI/coworld-tools) for imported
  players, commissioners, reporters, graders, diagnosers, and games; [Metta-AI/optimizers](https://github.com/Metta-AI/optimizers)
  for the active optimizer workbench.
