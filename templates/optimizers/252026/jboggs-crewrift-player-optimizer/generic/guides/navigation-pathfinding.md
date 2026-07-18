# Navigation & pathfinding — guide (generic tier)

Reference notes, design rationale, and negative results (3).

#### 1. Verify a baked asset is actually decoded and non-empty at runtime
`generic` · **negative result** · ⚠ _session-derived, unverified_

A precomputed/embedded artifact is only 'wired in' if a runtime parser actually decodes it; embedding the blob is not enough. Example: a baked binary was embedded but the loader set the parsed collection to an empty list and never decoded it, leaving the consuming code dead while the program ran on a fallback; separately, blobs set to empty strings under a 'TEMP disabled' comment silently disabled a whole subsystem. When a refactor splits produce-asset from consume-asset, assert the consumed collection is non-empty at startup so degenerate data fails loudly rather than silently. Watch for the related smell: fields read or initialized 'for X' but never assigned (placeholders for an unimplemented feature, a config field never set to anything but its disabled default) signal an incomplete refactor — grep for them.
  <sub>sources: codex:019dfe75-7dd6-7dd3-90af-84bb28fda415, codex:019dfea2-76a2-7ba0-996a-9be68ceee04f, opencode:ses_201972733ffexPIP9mq6yEDpqJ</sub>

#### 2. A subset-shortcut in front of a full search returns byte-identical results
`generic` · **negative result**

A biased BFS that only tries toward-target directions and falls back to a full BFS produces byte-identical output to always running the full BFS: fallback-on-failure equals full replacement when the primary method is a strict SUBSET of the fallback, because there is no path the biased method finds that the full method would not find first. To get a different result you must change the search itself, not add a subset-shortcut in front of it.
  <sub>sources: alpha_cog/AGENTS.md</sub>

#### 3. A recovery trigger must be able to observe the actual failure state
`generic` · **negative result** · ⚠ _session-derived, unverified_

A stuck/stall detector must not be gated on a precondition the bug itself makes impossible: a detector requiring 'path.len > 0 AND lastEmittedMask != 0' can never fire during an empty-path/noop failure that produces exactly path.len==0 and mask==0. When designing a recovery trigger, verify it can observe the ACTUAL failure state, not just a healthy-but-stalled state.
  <sub>sources: opencode:ses_20b7f9058ffeA36rC0WbRQYP6f</sub>
