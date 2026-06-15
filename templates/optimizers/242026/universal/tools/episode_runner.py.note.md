# episode_runner.py — note

**What it does.** The background-job layer that drives a league A/B and tracks it
locally for the dashboard. `run_episode` submits both arms (candidate, baseline)
via `league_eval.run_league_ab` in a daemon thread and records the run in a local
`RunIndex` keyed by a unique `run_id`; the dashboard polls status/result by that
id. The Observatory *is* the queue — this layer only holds the candidate/baseline
pairing the server doesn't track, plus run lifecycle (RUNNING → SUCCEEDED /
FAILED / CANCELLED).

**Key entry points.**
- `run_episode(request)` — adds a run row, spawns `_execute_run` in a thread,
  returns the `run_id` immediately (non-blocking dispatch).
- `_execute_run(run_id, request)` — runs both arms server-side; records FAILED on
  error (surfacing, then re-raising) and respects a user `cancel_run` via
  `should_cancel` without clobbering CANCELLED.
- `cancel_run(run_id)` — flips the local row to CANCELLED so the poll thread
  exits and the UI stops tracking it (the server job keeps running; no cancel API).
- `episode_status` / `episode_result` / `list_runs` — the read side the dashboard
  HTTP handlers call; `result_to_scrim` reshapes a verdict dict into the
  dashboard's "scrim" payload (per-arm wins/CIs/scores/kills + per-episode games).

**Why it matters to the loop.** It is the glue between the dashboard UI and the
eval engine: it makes the long-running A/B asynchronous and resumable-by-poll, and
it persists the local pairing index so a browser refresh still finds the run.

**Status: CURRENT.** Part of the current server-side eval stack; imports
`league_eval.run_league_ab` and `run_index.RunIndex`, and is consumed by
`dashboard.py`.
