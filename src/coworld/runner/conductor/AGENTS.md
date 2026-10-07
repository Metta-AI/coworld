# Conductor adapter

Experimental; owned by Scott (`@macromackie`). Production use is limited to Scott's approved GOTA XP pilot. Coordinate
with Scott before adding consumers, games, users, or production dependencies. APIs may change.

Read the [contracts](.contracts/index.md) and [integration guide](README.md) before editing this adapter. Keep game
semantics here and infrastructure lifecycle in Foundry. The game process owner manages exit observation, bounded
diagnostics, and graceful/forced shutdown together. The outer runner owns process-group cancellation.

Use erasable TypeScript in `.mts` files and explicit relative import extensions. Node executes these files directly;
Bazel supplies strict type checking. Keep the image build file list, installed command, and qualification scenario in
sync.

From the repository root inside the Nix environment, run:

```sh
bazel test //packages/coworld:conductor_typecheck_typecheck_test //packages/coworld:conductor_lint_test //packages/coworld/tests:conductor_adapter_test //packages/coworld:format_test
pnpm contracts:check
```

Run the real GOTA qualification described in the integration guide after process or image changes.
