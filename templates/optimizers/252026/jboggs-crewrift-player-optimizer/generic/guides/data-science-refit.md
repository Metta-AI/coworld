# Data-science refit (outer loop) — guide (generic tier)

Reference notes, design rationale, and negative results (3).

#### 1. Verify behavior from source-of-truth implementation, not inference or prose docs
`generic` · ⚠ _session-derived, unverified_ · _see related: U0266 (other tier)_

When a behavior matters, confirm it from the source-of-truth implementation the system actually runs, not from observed-output inference, a config/initializer read in isolation, or prose documentation. Inference and docs both drift from code: an incorrect assumption can be 'confirmed' by a sample that happened to match, and a stale claim in a design doc propagates into new work. Read the code path that actually executes (set-vs-add, initialization order, what does NOT happen) and treat any doc/code disagreement as a finding to reconcile, updating the stale source.
  <sub>sources: codex:019e1355-fd7e-77b2-8af2-3f93c0ae623a, codex:019e1357-835f-7442-bd46-7e911617621f, opencode:ses_1f6f88f62ffe6S4x2gevW9UGvE</sub>

#### 2. Benchmark before vectorizing and write idiomatic target-language code from the start
`generic` · **negative result**

Vectorization is not automatically faster -- benchmark first. Scoring ~289 candidate camera positions against a 128x128 frame by building (N,128,128) intermediate tensors was 2-3x SLOWER than a single-candidate score in a Python loop, because the large intermediates blow out L2 cache while the per-candidate form stays in L1 and the per-candidate numpy work ~ the Python call overhead. Conversely, replace O(n^2) nested-loop spatial dedup with a boolean occupancy mask (each kept hit stamps its (2r+1)-square neighborhood) and vectorise per-pixel matches with boolean-mask arithmetic plus an in-band out-of-bounds sentinel. When porting languages, write the idiomatic target form (numpy bincount/argmax/where/sliding_window_view) from the start -- a value-parity oracle catches algorithmic drift but never un-idiomatic encoding, so 'transliterate now, idiomatize later' cost a full second rewrite; but skip a numpy rewrite when it would worsen clarity for no real perf need (a branchy role-update state machine was left in loop form deliberately).
  <sub>sources: claude-code:1c7117ad-9bee-4658-8937-e92adbc1a6ae, players_checkouts/players/archive/players/among_them/coborg/PLAN.md</sub>

#### 3. Structure a lab notebook as one-file-per-entry with validated YAML frontmatter; do not use RAG
`generic` · **negative result** · ⚠ _session-derived, unverified_

For a research/experiment lab notebook at modest scale (e.g. ~56 entries), do NOT reach for a graph DB plus RAG: the graph DB is overkill and RAG actively HURTS because the notebook's value is multi-hop cross-references (reading several entries together reveals patterns like horizon-scaling or 'byte-identical output means the flag is not firing') that embedding retrieval fragments, plus a chicken-and-egg failure (the agent must know what to ask to retrieve it). Prefer one-entry-per-file with structured YAML frontmatter (id, title, hypothesis IDs, parameters, verdict/status, scores) plus a searchable prose body, a script-generated committed index, and a curated heuristics list (e.g. in AGENTS.md) solving discovery. Institutionalize the schema: document a field reference table and add a validate() in the index generator (required fields, enum validity, cross-field constraints, type checks, cross-ref integrity) that surfaces warnings WITHOUT blocking (in stdout and a validation_warnings field) so one malformed entry doesn't poison the rest; expect prose-vs-status drift on migration and re-run until grep is clean.
  <sub>sources: opencode:ses_20b14e3aaffe6TJnfnmV5DdVmT</sub>
