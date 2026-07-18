# Suspicion & belief modeling — guide (loop tier)

Reference notes, design rationale, and negative results (1).

#### 1. Model junction ownership with six states, keyed on connected-vs-disconnected
`loop` · ⚠ _session-derived, unverified_

Model a game-state belief at the granularity the decision logic actually acts on, not a coarser binary that discards the signal that matters. In the cogsguard territory game, junction ownership needs SIX states (unobserved, neutral, cogs-connected, cogs-disconnected, clips-connected, clips-disconnected) rather than binary owned/unowned, because the connected-vs-disconnected distinction (whether a captured junction is wired back to a team hub) is what the decision logic keys on; a binary belief throws that away.
  <sub>sources: codex:019e0850-2833-7773-a5e4-80ee662745c0</sub>
