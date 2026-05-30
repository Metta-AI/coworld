# Trace Artifact

A **trace** is an optional machine-readable timeline inside a [report](REPORT.md) zip. It lets a reporter expose the
facts it derived from replay, results, or logs without forcing consumers to parse the human render target.

## Producer

A reporter may include one trace in its report zip and point to it from the report's top-level `manifest.json`:

```json
{
  "trace": "trace.jsonl"
}
```

The trace path must have a `.jsonl` or `.json` extension.

## Shape

The trace payload is reporter-defined. Prefer JSON Lines for tick or event timelines so consumers can stream large
reports without loading the whole file.

Use the shared [event log](EVENT_LOG.md) schema for cross-episode table analytics. Use `trace` when the reporter needs a
richer nested record shape that is still useful to machines.

## See Also

- [Report](REPORT.md) for the containing zip and manifest.
- [Event log](EVENT_LOG.md) for the cross-reporter Parquet schema.
- [Reporter role](../roles/REPORTER.md) for the producer.
