# league_roster.py — note

**What it does.** Picks the league's top players as *runnable* experience-request
opponents. The server only accepts an opponent that is a live league membership
(competing, container ready) and unambiguous — a bare `player_name` with more than
one live version is rejected, and a stale `policy_version_id` from an old round
result "did not match an active runnable policy." So this module sources opponents
from the live-membership list and ranks them by recent round score (division
leaderboards are empty today), returning each chosen player's latest live pvid.

**Key entry points.**
- `fetch_top_players(client, *, league_id, exclude_player_id, top_n, ...)` —
  returns the top `top_n` distinct live members' `policy_version_id`s in score
  order, excluding yourself; raises if fewer than `top_n` live competitors exist.
  This is what `league_eval.resolve_roster` calls to fill the other 7 seats.
- `live_members(...)` — all live members (latest live version per player) ranked
  by best recent round score, unscored last; returns rows with `player_id`,
  `player_name`, `label`, `policy_version_id`, `score`. Also feeds the dashboard's
  per-seat opponent picker.
- `_best_score_by_player(...)` — scans completed rounds for each player's best
  round score.

**Why it matters to the loop.** Defines *who the candidate is measured against*.
A strong, varied live field is what keeps the A/B from saturating at the win-rate
ceiling, and sourcing from live memberships (not stale round-result pvids) is what
keeps a submitted request from being rejected as un-runnable.

**Status: CURRENT.** Part of the current server-side eval stack; directly
consumed by `league_eval.py` and `dashboard.py`.
