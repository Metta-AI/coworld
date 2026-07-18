# Build, package & submit — guide (generic tier)

Reference notes, design rationale, and negative results (1).

#### 1. Advance the pinned dependency on the lowest stack branch, not a local workaround
`generic` · **negative result** · ⚠ _session-derived, unverified_

When a CI failure traces to a pinned dependency that predates a needed API, fix it by advancing the pin on the LOWEST stack branch that requires it and rebasing descendants, rather than papering over it with a local parse/compat workaround in a top-of-stack commit. A green local build that hides a missing dependency field is the wrong fix. (Concrete instance: a RuntimeConfig.mismatchQuit-not-found build break root-caused to a lockfile pinning an older upstream commit.)
  <sub>sources: codex:019e8ae0-d849-7d12-9a7c-2b5e09ba75cf</sub>
