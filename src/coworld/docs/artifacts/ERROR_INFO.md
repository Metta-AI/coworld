# Error Info Artifact

The **error info artifact** is runner-written JSON describing a hosted episode failure.

## Producer

The hosted runner writes error info to `ERROR_INFO_URI` when the coordinator fails before a normal episode completion.
The local runner does not currently produce a separate error-info file.

## Contract

The runner-side JSON follows the `RunnerError` shape:

```json
{
  "error_type": "player_error",
  "message": "Player pod ... exited with code 1",
  "failed_policy_index": 0
}
```

Fields:

| Field                 | Required? | Purpose                                                                                                |
| --------------------- | --------- | ------------------------------------------------------------------------------------------------------ |
| `error_type`          | required  | Typed failure category. See [Error types](#error-types).                                               |
| `message`             | required  | Human-readable failure summary, truncated by the runner.                                               |
| `failed_policy_index` | optional  | Slot index of the failed policy when `error_type` is `"player_error"` and the runner can identify one. |

## Error types

| Type                      | Meaning                                                                                                                                                                                                                                                                                           |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `player_error`            | A player pod or local player container failed, or could not start. Carries `failed_policy_index` when the runner can identify the slot.                                                                                                                                                           |
| `game_unhealthy`          | The game process itself failed: it never served `/healthz`, or the game container exited non-zero before or during the episode. The message includes the exit code when available.                                                                                                                |
| `game_contract_violation` | The game became healthy but failed a route, WebSocket, or auth contract check such as `/client/player`, bad-token rejection, `/client/global`, or `/global`.                                                                                                                                      |
| `results_missing`         | The game exited successfully without writing `results.json`.                                                                                                                                                                                                                                      |
| `results_malformed`       | `results.json` exists but is not valid JSON or fails `manifest.game.results_schema`.                                                                                                                                                                                                              |
| `replay_missing`          | A replay was required but the game exited successfully without writing it.                                                                                                                                                                                                                        |
| `replay_unloadable`       | A replay load/check step could not relaunch the game from the replay or receive replay WebSocket data. The Kubernetes episode worker currently does not relaunch replay, so hosted episode jobs do not assign this type; certifier replay validation assigns it in its separate replay-load step. |
| `episode_timeout`         | The overall episode wall-clock expired and the runner could not attribute the failure to a more specific game, player, results, or replay condition.                                                                                                                                              |
| `crash`                   | An unexpected runner/coordinator failure outside the typed episode failure categories.                                                                                                                                                                                                            |

The backend may also synthesize an `error-info` response from stored job error fields when a persisted job failed before
an uploaded `ERROR_INFO_URI` object is available.

## Consumers

Error info can be consumed directly from hosted artifact routes or through the [episode bundle](EPISODE_BUNDLE.md)
`error_info` token. A failed bundle may contain `error_info.json` while other episode artifacts are absent.

## See Also

- [Lifecycle](../LIFECYCLE.md) for hosted failure handling.
- [Episode bundle](EPISODE_BUNDLE.md) for bundled failure artifacts.
