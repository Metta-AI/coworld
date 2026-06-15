# run_index.py — note

**What it does.** A tiny JSON-file index linking each local A/B `run_id` to its
state and its two server experience-request ids. The Observatory is the real queue
(it lists every experience-request with status); this index only records the
pairing the server doesn't know about, keyed by a unique `run_id` so many A/Bs for
the same `(candidate, baseline, role)` coexist independently.

**Key entry points.** The `RunIndex` class: `add(**fields)` (mints a `uuid4` hex
run_id, stamps `created_at`), `list()` (newest first), `get(run_id)`,
`update(run_id, **fields)`. Writes are atomic — a temp sibling file is written and
`os.replace`d onto the index so a concurrent `/api/runs` read never sees a
half-written file.

**Why it matters to the loop.** It is the persistence behind `episode_runner`: it
survives a dashboard restart and lets the UI re-find in-flight and completed runs,
mapping a local run back to the candidate/baseline pairing and the two server xreq
ids (so each episode's hosted replay stays reachable).

**Status: CURRENT.** Part of the current server-side eval stack; the storage layer
under `episode_runner.py`.
