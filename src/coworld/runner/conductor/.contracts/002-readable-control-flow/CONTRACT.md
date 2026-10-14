---
name: coworld-conductor-readable-control-flow
message: Keep modules focused and named for their behavior, with explicit control flow and established patterns.
---

## Rules

Give each module one understandable responsibility.
Name modules for the behavior or resource they own.
Do not create catch-all modules such as `utils`, `helpers`, `common`, or `misc`.
Create a module only when it has an actual responsibility; do not add placeholder files.
Split a module when the split reduces the context needed to understand a change, and keep cohesive code together when splitting would obscure its invariants.
Keep options and local result types beside the implementation that uses them.
Keep helpers private to their module until another caller needs them.

Extract a helper only when it names a real concept, collapses real duplication, or isolates an independent operation, never just to shorten a block.

Pass inputs and return results explicitly instead of relying on hidden side effects or ambient mutable state.
Separate logical phases with blank lines, and name intermediate values when nested calls hide the sequence.
Name values for what they hold, and include the unit in the name of a limit or duration whose type does not carry it.

Follow the area's established naming, placement, and structure instead of introducing a competing convention.
Use established libraries and ordinary library types for parsing, validation, and provider integration instead of recreating their behavior.

## Checks

Read a representative changed call from entry to result: can its inputs, effects, result, error path, and owner be understood without following a chain of forwarding helpers?
Compare that call before and after the change and confirm the caller needs no more local context than before.
For each new module or helper, name the behavior it owns and the concept, duplication, or independent operation that justifies it.
Search changed paths for catch-all module names and for helpers with a single caller.
Run the repository's formatter, linter, and type checks; they establish layout and types, not readability.

## Local adaptations

These conventions govern the TypeScript adapter and image builder in this directory.
The existing Coworld and Conductor wire formats remain unchanged.

Keep related statements together.
Use braces around control-flow bodies, including early returns.
Write outcome, configuration, and artifact objects across multiple lines so their fields are easy to scan.
Use descriptive names and include units for limits and durations, such as `maximumDiagnosticBytes` and `shutdownGracePeriodMs`.
Keep lifecycle decisions, awaited operations, cancellation, and cleanup explicit.
Preserve their ordering during cleanup.
Keep simple expressions inline.

```typescript
gameProcess.kill('SIGTERM')

await Promise.race([gameClosed, gracePeriodExpired])

if (!hasClosed) {
  gameProcess.kill('SIGKILL')
  await gameClosed
}

const diagnosticsArtifact = {
  name: 'diagnostics',
  path: 'diagnostics.log',
  mediaType: 'text/plain',
}
```

Read a changed lifecycle from entry to completion and interruption, and check its phase spacing, data shapes, names, and cleanup order.
