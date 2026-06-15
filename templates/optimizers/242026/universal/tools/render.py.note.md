# render.py — note

**What it does.** Renders the Crewrift policy dashboard as a single self-contained
HTML file (inline CSS + vanilla JS, no CDN, no build step) — the "Command Deck"
design with three tabs: Runs (existing league A/Bs + a launcher), Scrimmage (one
run's verdict detail with a per-seat slot inspector), and League (standings,
rounds, submissions, events). The Python side adapts the `data` dict from
`dashboard.py` into a `window.CREWRIFT` payload that a small in-page hyperscript
app renders.

**Key entry points.**
- `render_html(data)` — the public entry; returns the full HTML string
  `dashboard.py` serves as `index.html`.
- `scrim_payload(scrim)` — adapts one run's result into the Scrimmage-tab shape;
  called live by `dashboard.py`'s `/api/scrim` handler.
- `_build_payload`, `_build_league`, `_build_policy`, `_build_stats`,
  `_build_paired`, `_enrich_games` — internal builders that shape league data,
  pair candidate/baseline episodes by seed, and wire per-episode replay links
  (hosted `/watch?episode=` or local `/watch?replay=&manifest=`).
- `COLORS` — the 16-color crew palette (index == slot == self-color), mirroring
  the game and the metrics/results slot ordering.

**Why it matters to the loop.** Pure presentation: it turns the eval's verdict and
league data into the browser view. No eval logic, no network — it only formats.

**Status: CURRENT (support).** A presentation dependency of `dashboard.py`; carries
no eval logic of its own.
