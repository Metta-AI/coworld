# Event Log Artifact

An **event log** is an optional structured Parquet file inside a [report](REPORT.md) zip. It lets reporters expose
tick-aligned facts in a game-agnostic table shape.

## Producer

A reporter may include one event log in its report zip and point to it from the report's top-level `manifest.json`:

```json
{
  "event_log": "events.parquet"
}
```

The event log path must have a `.parquet` extension.

## Schema

Every event log uses the same column schema:

| Column | Type | Purpose |
| --- | --- | --- |
| `ts` | int64 | Episode tick when the event occurred. |
| `player` | int64 | Player slot for player-scoped events, or `-1` for global episode events. |
| `key` | string | Event name or stable stat key. |
| `value` | string | Event value, JSON-encoded when the value is structured. |

An empty event log should still be a well-formed zero-row Parquet table so consumers do not need a missing-file special
case.

## Determinism

The in-tree reference writer uses Snappy-compressed Parquet and a single row group. Byte-identical output depends on the
reporter image's pinned Parquet writer version because Parquet footers include writer metadata.

## Consumers

Event logs are the structured bridge from narrative reporting to policy analysis. Diagnosers and optimizers can use them
to tie policy behavior, game events, and interesting moments back to concrete episode ticks.

## See Also

- [Report](REPORT.md) for the containing zip and manifest.
- [Trace](TRACE.md) for richer reporter-defined machine timelines.
- [Reporter role](../roles/REPORTER.md) for the producer.
- [Diagnosis](DIAGNOSIS.md) and [optimizer outputs](OPTIMIZER_OUTPUTS.md) for likely downstream consumers.
