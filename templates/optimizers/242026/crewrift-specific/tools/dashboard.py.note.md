# dashboard.py — note

**What it does.** A local, self-serving HTTP dashboard (stdlib `ThreadingHTTPServer`)
for the Crewrift policy work. It pulls live league standings (`softmax_pull`) and
recent policy diffs (git log/diff over `players/`), lists your uploaded policy
names, and lets you pick a candidate/baseline/role in the browser and **Run a
server-side league A/B** via `episode_runner.run_episode` (which submits both arms
to the Observatory experience queue and streams the verdict in when done). It also
opens per-episode replays — hosted (`coworld replay-open --hosted`, no Docker) or
local (`coworld replay`) — reassembling the rich/typer-wrapped viewer URL from the
child process's stdout.

**Key entry points.** `main()` builds the ambient data and serves it. `Handler`
exposes the API: `/api/policies`, `/api/runs`, `/api/run` (POST → `run_episode`),
`/api/run/cancel`, `/api/status`, `/api/scrim`, and `/watch` (302-redirects to a
replay viewer URL). `build_ambient` assembles league + diff + policy data;
`league_roster_view` feeds the run dialog; `Viewers` manages the one live replay
container; `render.render_html` produces the page.

**Why it matters to the loop.** It is the human cockpit over the *same* server-side
eval engine — a convenient way to launch league A/Bs, browse standings/diffs, and
watch replays without typing CLI commands. It is **not** a separate eval method:
its Run button goes through `episode_runner` → `league_eval.run_league_ab`, the
league-faithful path.

**Status: CURRENT, with a caveat.** This dashboard (the *server-side* league-A/B
UI driving `episode_runner`/`league_eval`) is current. Do not confuse it with the
older **local-docker A/B dashboard** the orchestrator brief referred to as a
"cheap mechanism-check lab (not league-faithful)" — that role is mechanism
probing, but *this* file's `/api/run` clearly dispatches to the server-side league
A/B (`execution_backend` defaults to `k8s`, opponents come from live league
members), so as shipped here it is the current league dashboard. The only
remaining local-Docker behavior is optional *replay watching* (`coworld replay`),
which is a viewer convenience, not the eval.
