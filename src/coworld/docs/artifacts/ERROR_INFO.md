# Error Info Artifact

The **error info artifact** is runner-written JSON describing a hosted episode failure.

## Producer

The hosted runner writes error info to `ERROR_INFO_URI` when the coordinator fails before a normal episode completion.
The local runner does not currently produce a separate error-info file.

## Contract

The runner-side JSON follows the `RunnerError` shape:

```json
{
  "error_type": "policy_error",
  "message": "Player pod ... exited with code 1",
  "failed_policy_index": 0
}
```

Fields:

| Field | Required? | Purpose |
| --- | --- | --- |
| `error_type` | required | `"policy_error"` for failed player pods, `"crash"` for other coordinator failures. |
| `message` | required | Human-readable failure summary, truncated by the runner. |
| `failed_policy_index` | optional | Slot index of the failed policy when the runner can identify one. |

The backend may also synthesize an `error-info` response from stored job error fields when a persisted job failed before
an uploaded `ERROR_INFO_URI` object is available.

## Consumers

Error info can be consumed directly from hosted artifact routes or through the [episode bundle](EPISODE_BUNDLE.md)
`error_info` token. A failed bundle may contain `error_info.json` while other episode artifacts are absent.

## See Also

- [Lifecycle](../LIFECYCLE.md) for hosted failure handling.
- [Episode bundle](EPISODE_BUNDLE.md) for bundled failure artifacts.
