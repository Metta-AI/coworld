# metrics.py — note

**What it does.** A backend-agnostic per-episode + aggregate metrics tool. It
consumes the artifacts every episode produces — `results.json` (slot-indexed
arrays: names, scores, win, tasks, kills, imposter, crew, vote_*) and
`policy_agent_<slot>.log` (that seat's decisions) — whether they came from a local
`coworld run-episode` or an experience-request download (`antfarm_run.py`). Beyond
raw win-rate it computes **deduction quality**: vote accuracy = the fraction of a
seat's player-votes that targeted an actual imposter, parsed from "voting for
<color>" log lines mapped to slots via the slot-index==color-index invariant, plus
LLM-advisor fire/timeout/invalid counts.

**Key entry points.**
- `load_episode(ep_dir)` → `episode_metrics(ep)` — one episode's per-seat rows.
- `find_episodes(path)` — accepts a single episode dir, a run dir of `episode_*`/
  `out_*` subdirs, or one level deeper.
- `aggregate(episodes, candidate=None)` — rolls seats up by role (crew/imposter/
  all), optionally restricted to seats whose policy name contains `--candidate`;
  emits win-rate + Wilson CI, mean score, vote accuracy, vote timeouts, advisor
  fire rate.
- `main()` — CLI:
  `uv run python _harness/metrics.py <path> [--candidate <substr>] [--json]`.

**Why it matters to the loop.** This is the *diagnostic* layer the A/B verdict
can't give you: when a change doesn't move win-rate, metrics.py tells you whether
votes are landing on real imposters, whether the advisor is firing or timing out,
and where score is being lost — the evidence that picks the next lever.

**Status: CURRENT.** Part of the current server-side eval stack (offline
artifact analysis); consumes both local and downloaded experience-request output.
Note its own local `wilson()` (n==0 → hi=1.0) differs slightly from
`harness_core.wilson` (n==0 → hi=0.0); harmless for analysis but not the same
function.
