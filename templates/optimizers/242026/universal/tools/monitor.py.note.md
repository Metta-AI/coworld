# monitor.py — note

**What it does.** A standalone long-poll watcher of the Crewrift **Wood** league.
Every 15 minutes it snapshots the Wood division leaderboard and recent completed
Wood rounds, and prints a line only on a *meaningful change*: daveey's Wood rank
moving (with UP/DOWN arrow), a daveey policy other than the known `daveey-notsus:v2`
regression appearing in a Wood round (a graduation signal), or reaching #1. It
runs until stopped; each printed line is a monitor event.

**Key entry points.** `snapshot()` — fetches `/v2/division-leaderboards/{DV}` and
`/v2/rounds` (+ per-round detail) via `httpx` using a cogames token from
`softmax.auth`, returning `(rank, score, reps)`. `main()` — the poll loop holding
`prev_rank`/`prev_reps` and emitting only on change. The Wood league and division
ids are hardcoded.

**Why it matters to the loop.** The A/B verdict measures a change in isolation; the
league rank is the *real-world* outcome over time. This is the cheap always-on
signal that tells you when a newly uploaded policy has actually graduated into Wood
rounds or moved the standings — the gated, durable measure of success.

**Status: CURRENT.** Listed among the current server-side eval tools. Caveats
worth knowing for reuse: it is a *standalone* watcher (uses `softmax.auth` +
`httpx` directly, not the shared `harness_core`/`league_eval` stack), it is wired
to a specific division and the `daveey`/`daveey-notsus:v2` identifiers, and it
contains the one `try/except` in the eval stack — a deliberate poll-error guard so
a transient API hiccup doesn't kill the long watch. Per the memory note
`crewrift-watch-loop-needs-monitor`, run such a watch via the Monitor tool with an
until-loop, not a detached background shell with a long `sleep`.
