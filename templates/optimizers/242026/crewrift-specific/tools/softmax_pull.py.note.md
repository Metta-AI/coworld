# softmax_pull.py — note

**What it does.** Pulls live league context for the dashboard from the
Softmax/Observatory API and packages it into typed dataclasses. Because the
hosted-replay surface (`/v2/episode-requests`) is currently 404 and
`list_memberships(mine=True)` throws a schema-drift ValidationError, it builds the
softmax section from the endpoints that *do* work today — division leaderboards,
rounds + round detail, my submissions, and competition events — and deep-links each
row into the softmax.com Observatory web UI where replays remain watchable.

**Key entry points.**
- `fetch_softmax(league_id, ...)` — the public entry; returns a `SoftmaxContext`
  (league, divisions/leaderboards, recent rounds, my submissions, events, hosted-
  replay status) that `dashboard.py` calls `.to_dict()` on.
- `probe_hosted_replays(client)` — feature-detects the hosted-replay endpoint,
  catching *only* the HTTP status error so the section degrades to web deep-links
  and reports why; if the endpoint returns, in-dashboard click-to-watch lights up
  automatically.
- `league_url` / `submission_url` — build Observatory web deep-links.
- The `*View` / `*Row` dataclasses define the league section's shape.

**Why it matters to the loop.** It surfaces the *outcome* side in the dashboard —
where your policies sit on the leaderboards, what happened in recent rounds, and
which submissions are live — the context that frames every A/B decision.

**Status: CURRENT (support).** A data-fetch dependency of `dashboard.py`; it
already accommodates the live API's current gaps (null leaderboards coerced to
`[]`, the 404 hosted-replay probe, the membership schema drift), so it is the
working pull path today.
