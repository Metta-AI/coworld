# league_eval.py — note

**What it does.** The harness that actually runs a league A/B over Observatory
experience requests. Each arm (candidate, baseline) is one
`POST /v2/experience-requests`: the requester takes a single forced-role seat and
the league's top seven players fill the rest; the game runs on k8s. Both arms run
concurrently (the server parallelizes episodes per request), and the per-seat
`results.json` artifacts feed shared Wilson verdict math.

**Key entry points.**
- `run_league_ab(client, req, ...)` — top-level orchestrator: resolves both
  policy names to pvids up front (no server cancel API, so a bad name must fail
  before any submit), resolves the 7-opponent roster, submits both arms in a
  2-worker `ThreadPoolExecutor`, and assembles the verdict dict (`wins`, Wilson
  CIs, scores, kills, vote_timeouts, per-episode `games`, the two xreq ids). A
  failed arm sets an `abort` Event so the sibling's poll exits promptly.
- `run_arm(http, body, ...)` — submits one request and polls to terminal with a
  transient-status retry set (`404/425/429/5xx`) and a `stall_grace_seconds`
  fail-fast for wedged sims (zero episodes complete → declared wedged). Harvests
  per-episode `results.json`, participants, replay urls, and ereq ids.
- `build_request_body(...)` — the request payload; pins the seat *inside* the
  `requester` object (`requester.slot`) alongside top-level `opponents`, because
  the server rejects a top-level `requester_slot` next to a `requester`.
- `forced_slots_config` / `requester_slot_for_role` — seed-deterministic forced
  imposter-slot layout (via `harness_core`); the requester's role is chosen by
  *picking a seat* of that role, not by changing the layout.
- `resolve_roster` (uses `league_roster.fetch_top_players`), `arm_tally`,
  `_episode_games`, `arm_timeout_seconds`, `stall_grace_seconds`, `RunCancelled`.

**Why it matters to the loop.** This is the engine of the eval — every A/B verdict
(`eval.py` CLI and the dashboard's Run button) flows through `run_league_ab`. It
encodes the league-faithful field, the forced-role seating, the concurrency, and
the timeout/wedge handling that make a verdict trustworthy.

**Status: CURRENT.** Core of the current server-side eval stack. NOTE: an older
memory note (`crewrift-xreq-roster-api-change`) listed league_eval.py as
predating the 2026-06-12 unified-roster rework — but *this* copy is already
patched to the post-rework shape (the `requester`-object-with-inner-`slot` body
and its inline comment about the server's `requester.slot cannot be supplied with
requester_slot` validation), so it is current, not stale. It reaches into
`client._http_client` / `client._headers()`, so a coworld upgrade renaming those
would break it loudly.
