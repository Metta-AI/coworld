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
| [Debug archive](DEBUG_ARCHIVE.md) | Hosted runner | Hosted `DEBUG_URI` aggregate log zip |
| [Error info](ERROR_INFO.md) | Hosted runner | Hosted `ERROR_INFO_URI`, episode bundle `error_info` token |
| [Episode bundle](EPISODE_BUNDLE.md) | Bundling layer | On-demand zip assembled for post-episode consumers |

## Supporting-Role Outputs

| Artifact | Producer | Where it appears |
| --- | --- | --- |
| Report output | Reporter | `report_output` message over the reporter's `/report` WebSocket, in the declared `output_format` (see [Reporter role](../roles/REPORTER.md)) |
| [Grade](GRADE.md) | Grader | `COGAME_GRADE_URI` JSON |
| [Diagnosis](DIAGNOSIS.md) | Diagnoser | `COGAME_DIAGNOSIS_URI` zip |
| [Optimizer outputs](OPTIMIZER_OUTPUTS.md) | Optimizer | Workbench side effects and optional plan artifacts |
| [Round decisions](ROUND_DECISIONS.md) | Commissioner | `round_complete` decisions recorded by the platform |

### Legacy reporter zip artifacts (superseded)

The reporter previously wrote a zip to `COGAME_REPORT_URI`. That contract is superseded by the WebSocket reporter
service above; these pages are retained because the in-tree paintarena legacy reporters still produce them.

| Artifact | Producer | Where it appears |
| --- | --- | --- |
| [Report (legacy)](REPORT.md) | Legacy reporter | `COGAME_REPORT_URI` zip |
| [Event log (legacy)](EVENT_LOG.md) | Legacy reporter | Optional Parquet entry inside a report zip |
| [Trace (legacy)](TRACE.md) | Legacy reporter | Optional JSON/JSONL entry inside a report zip |

See [README.md](../README.md) for the role model and artifact flow.
