# antfarm_run.py — note

**What it does.** A standalone launcher that runs coworld episodes on **Antfarm**
via Observatory experience requests and downloads every resulting artifact. It
POSTs `/v2/experience-requests` with `execution_backend=antfarm`, polls the parent
to terminal, then for each completed child episode downloads results.json, game
logs, per-agent policy logs, and the public-S3 replay (and saves errors for failed
children). It supports self-play (one owned pvid across all 8 seats), explicit
opponents by name or pvid, and a division `--top-n` fill, with transient-failure
resubmits (502/timeout) and arbitrary `--game-config KEY=VALUE` overrides. Note
that prod Observatory is wired to *staging* Antfarm, and every resolved policy must
be Antfarm-registered or dispatch fails.

**Key entry points.** `build_request(a)` — assembles the request body. `main()` —
the submit/poll/download driver, writing a per-xreq run dir of `episode_NN/`
artifact folders + a `summary.json`. Helpers: `submit_once` (server-error retry),
`poll_until_terminal`, `all_failures_transient` (decides whether to resubmit).

**Why it matters to the loop.** This is the artifact-harvesting path that feeds
`metrics.py` and the authoritative replay-decode oracle (`replay_mine.nim`) — it's
how you pull the raw logs + replays for deep diagnosis, distinct from the
league-faithful A/B verdict.

**Status: SUPERSEDED (will 422 until patched).** `build_request` emits the
**pre-rework** request shape: top-level `opponents` / `policy_version_ids` /
`top_n` and a `target` block, with **no** `requester` object and no per-seat
`roster`. The `/v2/experience-requests` endpoint was reworked on 2026-06-12 to a
unified `roster` body (one entry per seat, `policy_ref`); the old requester/
opponents shape now 422s (memory note `crewrift-xreq-roster-api-change`). The
league A/B path (`league_eval.py`) was already updated to the post-rework body;
this antfarm launcher predates it and must be patched to the unified `roster`
shape before it will dispatch again.
