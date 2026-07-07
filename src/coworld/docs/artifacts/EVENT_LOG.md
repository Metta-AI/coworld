# Event Log Artifact

> **Reporter v2 (spec 0061).** The event log is the `event-log` typed
> [output part](REPORT.md): the reporter emits a list of typed event records through the
> `output` tool, and the platform host writes the Parquet file with pinned deterministic
> settings. See the [Reporter role](../roles/REPORTER.md).

An **event log** is a structured Parquet [output part](REPORT.md). It lets reporters expose
tick-aligned facts in a game-agnostic table shape.

## Producer

A reporter declares an `event-log` part in its version attributes, then produces it one of two
ways depending on hosting mode:

- **Bureau (platform-hosted):** the reporter emits a list of `{ts, player, key, value}` records via
  `output.emit(name, event-log(...))`. The host validates the records against the fixed schema below
  and writes the `.parquet` object itself — a Bureau reporter never hand-serializes Parquet.
- **Self-hosted (external):** the reporter serializes its **own** Parquet matching the fixed
  4-column schema below and POSTs it to the outputs API; the server validates the submitted Parquet
  against that schema. Getting the Parquet bytes right is the external reporter's responsibility.

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

On the host-written (Bureau) path the host writer uses Snappy-compressed Parquet, a single row
group, and a pinned writer version, so identical emitted records produce byte-identical Parquet —
determinism is by construction, not reporter discipline. For external submissions the reporter
writes its own Parquet, so Parquet-level determinism is the reporter's responsibility (the server
validates the schema, not the byte layout).

## Consumers

Event logs are the structured bridge from narrative reporting to policy analysis. Diagnosers and optimizers can use them
to tie policy behavior, game events, and interesting moments back to concrete episode ticks.

## See Also

- [Report outputs](REPORT.md) for the part contract and output catalog.
- [Trace](TRACE.md) for the host-written record of the run itself.
- [Reporter role](../roles/REPORTER.md) for the producer.
- [Diagnosis](DIAGNOSIS.md) and [optimizer outputs](OPTIMIZER_OUTPUTS.md) for likely downstream consumers.
