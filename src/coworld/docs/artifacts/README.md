# Artifact Reference

Artifacts are the durable outputs that make a Coworld episode useful after it runs. Roles describe who produces or
consumes something; artifact pages describe the thing itself.

## Episode Artifacts

| Artifact | Producer | Where it appears |
| --- | --- | --- |
| [Results](RESULTS.md) | Game | Local `results.json`, hosted `RESULTS_URI`, episode bundle `results` token |
| [Replay](REPLAY.md) | Game | Local `replay`, hosted `REPLAY_URI`, episode bundle `replay` token |
| [Game logs](GAME_LOGS.md) | Game container / runner | Local `logs/game.*.log`, hosted `DEBUG_URI`, episode bundle `game_logs` token |
| [Player logs](PLAYER_LOGS.md) | Player containers / runner | Local `logs/policy_agent_{slot}.log`, hosted `POLICY_LOG_URLS`, episode bundle `player_logs` token |
| [Player artifact](PLAYER_ARTIFACT.md) | Player containers | Local `policy_artifact_{slot}.zip`, hosted `PLAYER_ARTIFACT_UPLOAD_URLS`, episode bundle `player_artifact` token |
| [Debug archive](DEBUG_ARCHIVE.md) | Hosted runner | Hosted `DEBUG_URI` aggregate log zip |
| [Error info](ERROR_INFO.md) | Hosted runner | Hosted `ERROR_INFO_URI`, episode bundle `error_info` token |
| [Episode bundle](EPISODE_BUNDLE.md) | Bundling layer | On-demand zip assembled for post-episode consumers |

## Supporting-Role Outputs

| Artifact | Producer | Where it appears |
| --- | --- | --- |
| [Report](REPORT.md) | Reporter | Target `/reporter` service writes a zip to `report_uri`; one-shot reporters write to `COGAME_REPORT_URI` |
| [Render](RENDER.md) | Reporter | Safe embeddable `.md`/`.html` entry the platform renders from a report zip |
| [Event log](EVENT_LOG.md) | Reporter | Optional Parquet entry inside a report zip |
| [Trace](TRACE.md) | Reporter | Optional JSON/JSONL entry inside a report zip |
| [Grade](GRADE.md) | Grader | `COGAME_GRADE_URI` JSON |
| [Diagnosis](DIAGNOSIS.md) | Diagnoser | `COGAME_DIAGNOSIS_URI` zip |
| [Optimizer outputs](OPTIMIZER_OUTPUTS.md) | Optimizer | Workbench side effects and optional plan artifacts |
| [Round decisions](ROUND_DECISIONS.md) | Commissioner | `round_complete` decisions recorded by the platform |

See [README.md](../README.md) for the role model and artifact flow.
