---
name: coworld-conductor-module-boundaries
message: Give decisions and state one owner, with explicit dependency direction.
---

## Rules

Give each operation and durable fact one owner.
Keep domain decisions separate from provider transport, storage, and terminal rendering.
Pass explicit inputs and results across those boundaries.
Use the nearest package contract to identify allowed dependencies and public entry points.
Import another package only through a declared dependency and its public entry points, never its private modules; keep relative imports inside the owning package.
Consume another repository only through versioned artifacts or explicitly configured endpoints, never through a sibling checkout or an untracked filesystem path.
Keep test fixtures out of production code and builds.

Prefer modules or folders for internal organization.
Add a package for a current ownership, runtime, dependency, or reuse boundary.
Keep cohesive state transitions together.
An abstraction should reduce the decisions and internal knowledge required of its callers; a forwarding layer alone does not establish a useful boundary.

Use the same execution path for equivalent local and deployed behavior; infrastructure adapters may differ.
When replacing a boundary, update consumers, exports, commands, and documentation together.
Account for stored data and active consumers.
Remove superseded paths, options, dependencies, fixtures, and guidance when no current need remains.
Give a necessary temporary path an owner and removal condition.

## Checks

Trace an affected operation from entry point to result.
Identify the owner of each decision and state transition.
Inspect package manifests, public exports, and outside imports together.
Confirm that no import resolves to another package's private module, a sibling checkout, or an untracked path, and that production builds contain no fixtures.
Can a caller use the operation without knowing its private sequencing or repairing its result?
Use the owning workspace's existing checks.

## Local adaptations

These conventions govern the TypeScript adapter and image builder in this directory.
The existing Coworld and Conductor wire formats remain unchanged.

Extract the complete behavior rather than separate state, event, and cleanup files.
Shared protocol types describe the wire boundary only.
Use explicit named exports at intentional folder and package boundaries.
Outside consumers use that entry point; implementation imports remain within the owner.
Keep modules private until another production consumer needs their API.
A folder entry point defines visibility, not just a shorter import path.
Preserve tool-required entry points and export formats.
Executable scripts may directly compose sibling modules within their owning folder.
Add nested folders for a concrete responsibility or dependency boundary.
Keep ordinary glue inline.

Confirm a changed caller does not reach through a public boundary or duplicate lifecycle state.
