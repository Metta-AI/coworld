---
name: coworld-conductor-readable-control-flow
message: Make lifecycle phases, decisions, and data shapes easy to read.
---

# Readable control flow

These conventions govern the TypeScript adapter and image builder in this directory. The existing Coworld and Conductor wire formats remain unchanged.

## Rules

- Separate logical phases with blank lines. Keep related statements together.
- Use braces around control-flow bodies, including early returns.
- Write outcome, configuration, and artifact objects across multiple lines so their fields are easy to scan.
- Name intermediate values when nested I/O, parsing, validation, or construction hides the sequence.
- Use descriptive names and include units for limits and durations, such as `maximumDiagnosticBytes` and `shutdownGracePeriodMs`.
- Keep lifecycle decisions, awaited operations, cancellation, and cleanup explicit. Preserve their ordering during cleanup.
- Keep simple expressions inline. Extract a complete operation when it gives the caller a meaningful step.

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

## Checks

Read a changed lifecycle from entry to completion and interruption. Check phase spacing, data shapes, names, and cleanup order. The formatter checks layout; it cannot establish readability.
