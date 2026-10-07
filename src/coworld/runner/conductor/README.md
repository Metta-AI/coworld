# Conductor native integration

This optional adapter runs a game-hosted Coworld through Conductor's native process protocol. It retains the existing
`COGAME_*` file handoff and does not change the local/Kubernetes episode runners, manifests, policy uploads or XP
routing. Game rules and policy isolation remain with the approved game image.

The first qualification uses unchanged Gods of the Arena (GOTA). Only game-hosted files are supported here. Human input,
platform-hosted player containers, policy secrets and model calls are not implemented by this adapter. In particular,
LLM games still need their supported `COWORLD_LLM_ENDPOINT` integration before entering this path.

## Build and run locally

Use the repository-pinned Node runtime and Docker. The adapter uses erasable TypeScript in `.mts` files, which Node
executes directly. Bazel checks the types separately. Build Conductor's native launcher in a Foundry checkout:

```sh
mise exec -- pnpm --filter @softmax/conductor-world-runner build
```

From this directory, build a derived game image with the compiled `server.mjs` artifact:

```sh
node build-image.mts \
  --runner /path/to/foundry/workspaces/conductor/worlds/native-runner/dist/server.mjs \
  --game-image public.ecr.aws/q5f4m8t9/cogames@sha256:afa8698675dc3ac14700eb7c77c7ef262ef1933b2658f85ee41e7b94c6431bbb \
  --tag coworld-conductor-gota:local
```

This is the GOTA image qualified on 2026-10-06, not a moving latest tag. The helper requires an immutable game image,
builds Linux/amd64, prints the resulting image identity, and removes its temporary context. The image adds Node and
these adapters; the game executable is unchanged. The game base must support Node 24's Linux/glibc dependencies. This
image was qualified on Ubuntu 24.04; other bases need their own qualification.

From Foundry, run the checked-in scenario:

```sh
mise exec -- pnpm --filter @softmax/conductor-worlds qualify-native \
  /path/to/metta/packages/coworld/src/coworld/runner/conductor/examples/gota.json
```

The scenario has ten idle BASIC policies and a fixed seed. GOTA clamps its requested short episode to 3000 ticks. This
checks transport, compatibility and deterministic output; it is not a representative policy-performance benchmark.
Conductor saves the two results, replay bytes, hashes, lifecycle events and elapsed times in its local scenario state.
Compare real policies and full episode configurations before drawing performance conclusions.

## Implementation

Read the [adapter contracts](.contracts/index.md) before editing.

- `game-hosted.mts` composes one episode.
- `game-process.mts` owns the child process, bounded diagnostics and shutdown.
- `game-outcome.mts` reads game markers and waits for a complete outcome within the deadline.
- `episode-files.mts` prepares the game inputs and publishes the result/artifact manifest.
- `protocol.mts` describes the consumed process envelope and the adapter's output types.
- `build-image.mts` assembles the approved game image and removes its temporary build context.

## Adapter boundary

The launcher validates the versioned input and supplies `WORLD_INPUT_PATH`, `WORLD_OUTPUT_PATH` and
`WORLD_SCRATCH_PATH`. Its build emits canonical JSON schemas beside `server.mjs`. Roles must be contiguous `seat-0`,
`seat-1`, and so on. The adapter constructs the existing seats/config documents, passes file URIs to the installed game,
and treats complete results plus replay as the completion marker. It validates one finite score per seat. The game
remains responsible for its own configuration and result semantics.

The adapter stops the game's serving process after collection; Conductor enforces the overall deadline and kills the
process group. The adapter returns either a completed result or a structured game/player failure. Complete results and
replay take precedence over a failure marker. It preserves resolved player names and metadata, supplies canonical seat
artifact URIs, and adds per-run tokens. Results, replay and a bounded 64 KiB diagnostic log are declared for private
collection. Seat logs, player status and policy bytes remain in scratch space.

For local development, keep the installed command fixed to:

```json
["node", "/opt/worlds/game-hosted.mts", "/usr/local/bin/polyworld"]
```

Public world-run requests cannot select executables or images. This adapter is a local integration proof; deployment,
scoped Metta service access, XP cohort routing and rollback remain separate rollout work.
