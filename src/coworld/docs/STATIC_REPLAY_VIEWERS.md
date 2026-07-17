# Static Replay Viewers

Use a static replay viewer when a replay should open entirely in the browser without starting the game image. A viewer
is a game-owned directory of HTML, JavaScript, WASM, styles, models, textures, and other browser assets. Coworld treats
the directory as an opaque program: it requires an `index.html`, supplies the replay URL, and does not prescribe the
replay format, renderer, WASM ABI, or internal file layout.

This is the implementation guide for a Coworld author or coding agent.

## Runtime Contract

Observatory opens the uploaded `index.html` with the episode replay URL in the `replay` query parameter:

```text
https://viewer.example/<immutable-coworld-version>/index.html?replay=https%3A%2F%2F...%2Freplay.replay
```

The viewer must:

1. Read `new URLSearchParams(location.search).get("replay")`.
2. Fetch those opaque replay bytes. Hosted replay URLs permit browser CORS; local tests must serve the replay with
   equivalent CORS headers.
3. Reconstruct public presentation state and render it without a game container or other game-owned server.
4. Use relative URLs for files inside the bundle so the content-addressed hosting prefix can change.
5. Fail visibly when loading, parsing, resimulation, or rendering fails.

The bundle may be a small HTML/JavaScript viewer, a Three.js/WebGL application, a Bitworld viewer backed by WASM, or
another static browser program. There is no required `viewer.wasm`, JavaScript API, or presentation schema.

## Choose The Replay Producer

| Replay contains | Bundle normally contains | Preferred sharing boundary |
| --- | --- | --- |
| Public frames, snapshots, or events ready for presentation | Parser/reconstructor, shared renderer, controls, assets | Use the same presentation model and renderer as the live global viewer |
| Actions, inputs, or deterministic state deltas | Version-matched game core compiled to WASM, shared presentation adapter and renderer, controls, assets | Compile the same rules, replay parser, state transitions, and presentation code as the native game |

A larger WASM bundle is preferable to a second implementation of game behavior. It is fine to compile code that replay
viewing does not strictly need. Do not copy mechanics into a browser-specific implementation merely to reduce bundle
size.

Some browser-specific glue is unavoidable: fetching replay bytes, driving playback from the browser clock, exporting a
small WASM API, or adapting presentation packets to an existing renderer. Keep that glue thin. It must not independently
implement rules, replay reconstruction, seeking semantics, public-state construction, or rendering behavior. When the
native server and browser need the same replay lifecycle, extract a shared `ReplayRuntime`-style component and put only
the native HTTP/WebSocket and browser/WASM boundaries around it.

## Package And Manifest

Generate the viewer into a gitignored build directory and name only that directory in `coworld_manifest.json`:

```json
{
  "game": {
    "replay_viewer": {
      "bundle": "build/static-replay-viewer"
    }
  }
}
```

The bundle directory must:

- contain `index.html` at its root;
- contain regular files only, with no symlinks or paths escaping the directory;
- remain within the Coworld package root;
- contain at most 4,096 files, 256 MiB compressed, and 512 MiB uncompressed.

On upload, Coworld creates a deterministic archive, uploads it content-addressed, and replaces the authored path in the
stored manifest with `sha256:<digest>`. Extracted assets and public responses are marked
`public, max-age=31536000, immutable`, so generated bundles should not be committed merely to make them durable.

Omit `game.replay_viewer` to retain the version-matched game-container replay path.

## Required Coworld Build Hook

Every manifest with a source bundle directory must provide an executable:

```text
tools/build_replay_viewer.sh
```

`coworld build` runs it before writing the hydrated manifest, with the resolved absolute bundle directory as its only
argument and the manifest template directory as its working directory:

```text
tools/build_replay_viewer.sh /absolute/path/to/coworld/build/static-replay-viewer
```

The hook is part of the build contract. It must:

- exit nonzero when dependencies, compilation, or asset generation fails;
- recreate the output directory, rather than overlaying files from an older build;
- build from the same checked-in sources and dependency locks as the uploaded game image;
- produce `index.html` and every referenced asset without requiring a later manual step;
- avoid uploading, publishing, or mutating external state itself.

A minimal shape is:

```bash
#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
output_dir="$1"
if [[ "${output_dir}" != /* || "${output_dir}" == "/" || "${output_dir}" == "${repo_dir}" ]]; then
  echo "unsafe bundle output: ${output_dir}" >&2
  exit 1
fi

rm -rf "${output_dir}"
mkdir -p "${output_dir}"

# Compile shared sources, copy renderer assets, and write index.html here.
```

Keep the hook itself, WASM/browser entrypoints, adapters, dependency locks, and source assets in git. Keep its generated
output in `.gitignore`.

## Verification

Before uploading a new Coworld version:

| Check | Evidence |
| --- | --- |
| Clean build | Add a sentinel file to the output, rerun the hook, and confirm the sentinel is gone |
| Self-contained bundle | Serve the bundle over local HTTP; no game container is running |
| Replay compatibility | Load a replay produced by the same Coworld version and representative historical fixtures |
| Playback | Autoplay, pause, seek, speed, loop/end behavior, and resize work as intended |
| Presentation parity | Compare representative live and replay public frames or screenshots |
| Deterministic WASM parity | Native and WASM replay execution agree across seeds, seeking, and keyframes |
| Failure behavior | Missing, corrupt, and incompatible replay bytes produce a visible error |
| Build integration | Run `coworld build`; confirm the hook runs and the hydrated manifest points at the generated bundle |
| Upload integration | Run `coworld upload-coworld`; confirm it finds that bundle and the stored manifest contains its digest |

Run the browser test on both x86 and ARM when the viewer contains WASM or architecture-sensitive assets. During the
current rollout, also retain and test the game image's legacy replay mode: local certification still probes
`/client/replay` and `/replay`, while hosted Observatory prefers the declared static bundle.

## Agent Handoff Checklist

An implementation is ready when an agent can answer yes to each question:

- Does `index.html?replay=<url>` load the replay with no game container?
- Does the manifest name only the generated bundle directory?
- Is `tools/build_replay_viewer.sh` executable, clean-building, and invoked successfully by `coworld build`?
- Are generated files gitignored while every source input is committed?
- Are mechanics, replay reconstruction, presentation construction, and rendering shared with live execution wherever
  possible?
- Is any remaining browser-only logic limited to an explicit environment adapter?
- Do real-browser tests cover a current replay, presentation parity, controls, and visible failure behavior?

## See Also

- [Replay artifact](artifacts/REPLAY.md) — stored replay bytes and fallback behavior.
- [Game role](roles/GAME.md) — live container and replay contracts.
- [Authoring a Coworld](AUTHORING.md) — the full build, certification, upload, and hosted-verification ladder.
