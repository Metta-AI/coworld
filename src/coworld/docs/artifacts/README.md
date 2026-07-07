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
| [Report outputs](REPORT.md) | Reporter | Declared, typed output parts emitted via the `output` tool, stored per part (spec 0061) |
| [Render](RENDER.md) | Reporter | Safe self-contained `render-html`/`render-markdown` output part the platform embeds |
| [Event log](EVENT_LOG.md) | Reporter | `event-log` output part — host-written Parquet with the fixed 4-column schema |
| [Trace](TRACE.md) | Platform host | Host-written `trace.jsonl` audit record beside a run's output parts |
| [Grade](GRADE.md) | Grader | `COGAME_GRADE_URI` JSON |
| [Diagnosis](DIAGNOSIS.md) | Diagnoser | `COGAME_DIAGNOSIS_URI` zip |
| [Optimizer outputs](OPTIMIZER_OUTPUTS.md) | Optimizer | Workbench side effects and optional plan artifacts |
| [Round decisions](ROUND_DECISIONS.md) | Commissioner | `round_complete` decisions recorded by the platform |

See [README.md](../README.md) for the role model and artifact flow.
