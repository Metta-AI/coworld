# Tool sources

Where each verbatim copy in this `tools/` directory came from. Two repos are
involved:

- **Eval/harness consumer repo** — `daveey/crewrift` (the project workspace). All
  the Python eval-stack tools live in its `_harness/` directory.
- **Bot repo** — `Metta-AI/coworld-crewrift` (the crewrift coworld + the notsus
  player). Checked out locally as `_crewrift-repo/` (and per-experiment working
  copies like `_crewrift-0136/`). Holds the Nim sim, the player, the LLM advisor,
  and the build Dockerfile.

| Tool file (here)      | Original repo path                          | Repo                          |
| --------------------- | ------------------------------------------- | ----------------------------- |
| `eval.py`             | `_harness/eval.py`                          | `daveey/crewrift`             |
| `league_eval.py`      | `_harness/league_eval.py`                   | `daveey/crewrift`             |
| `league_roster.py`    | `_harness/league_roster.py`                 | `daveey/crewrift`             |
| `harness_core.py`     | `_harness/harness_core.py`                  | `daveey/crewrift`             |
| `metrics.py`          | `_harness/metrics.py`                       | `daveey/crewrift`             |
| `episode_runner.py`   | `_harness/episode_runner.py`                | `daveey/crewrift`             |
| `run_index.py`        | `_harness/run_index.py`                     | `daveey/crewrift`             |
| `monitor.py`          | `_harness/monitor.py`                       | `daveey/crewrift`             |
| `antfarm_run.py`      | `_harness/antfarm_run.py`                   | `daveey/crewrift`             |
| `dashboard.py`        | `_harness/dashboard.py`                     | `daveey/crewrift`             |
| `render.py`           | `_harness/render.py`                        | `daveey/crewrift`             |
| `softmax_pull.py`     | `_harness/softmax_pull.py`                  | `daveey/crewrift`             |
| `advisor.py`          | `players/notsus/advisor.py`                 | `Metta-AI/coworld-crewrift`   |
| `replay_mine.nim`     | `src/crewrift/replay_mine.nim`              | `Metta-AI/coworld-crewrift`   |
| `Dockerfile.llm`      | `players/notsus/Dockerfile.llm`             | `Metta-AI/coworld-crewrift`   |

## Notes on the mapping

- The `_harness/` tools import each other as flat siblings (`import league_eval`,
  `import harness_core as hc`, `import render`, `import softmax_pull`,
  `import episode_runner as er`). They also import `queue_models.ExperienceRequest`
  and `run_index.RunIndex`, which live in the same `_harness/` directory
  (`queue_models.py` is a harness sibling not copied into this `tools/` set).
- `harness_core.py` self-identifies its path in its docstring ("this file is
  `_harness/harness_core.py`"); `metrics.py`, `antfarm_run.py`, and `dashboard.py`
  all show `uv run python _harness/<tool>.py` usage, confirming the `_harness/`
  home.
- `advisor.py` and `Dockerfile.llm` are bot-repo files under `players/notsus/`;
  `Dockerfile.llm` itself copies `players/notsus/advisor.py` into the image, and
  its build stage mirrors `players/notsus/Dockerfile`.
- `replay_mine.nim` is an analysis oracle added under the bot repo's
  `src/crewrift/` (alongside `replays.nim`/`sim.nim`, which it imports as
  `./replays` and `./sim`). It is present in working copies such as
  `_crewrift-0136/`; build it from within a crewrift bot-repo checkout.
