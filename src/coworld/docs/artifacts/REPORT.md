# Report Artifact (Legacy)

> **Superseded.** This zip-to-`COGAME_REPORT_URI` contract is the legacy reporter output. Current reporters are
> persisted WebSocket services that emit a `report_output` message in a declared `output_format`; see the
> [Reporter role](../roles/REPORTER.md). This page is retained because the in-tree paintarena legacy reporters still
> produce it. Do not build new reporters against this contract.

The **report artifact** is a reporter-written zip that explains or summarizes one completed episode.

## Producer

The [reporter role](../roles/REPORTER.md) writes one zip to `COGAME_REPORT_URI`. Reporters consume an
[episode bundle](EPISODE_BUNDLE.md), decide which episode evidence matters, and write a report for humans, UIs, agents,
or downstream supporting roles.

## Zip Contents

A report zip may contain Markdown, HTML, JSON, Parquet, images, or other reporter-owned files. It should include a
top-level `manifest.json` that describes the important entries:

```json
{
  "reporter_id": "paint-arena-summarizer",
  "render": "summary.md",
  "event_log": "events.parquet",
  "trace": "trace.jsonl"
}
```

Fields:

| Field | Required? | Purpose |
| --- | --- | --- |
| `reporter_id` | recommended | Reporter self-identification, conventionally matching the runnable id in `manifest.reporter[]`. |
| `render` | optional | Path inside the zip to one `.md` or `.html` file that UIs should render. |
| `event_log` | optional | Path inside the zip to one `.parquet` file following the [event log](EVENT_LOG.md) schema. |
| `trace` | optional | Path inside the zip to one `.jsonl` or `.json` machine-readable trace artifact. |

All other files in the zip are reporter-defined. Consumers should use `manifest.json` to find renderable, trace, and
structured entries instead of assuming fixed filenames.

## Determinism

Reporters are not required to be byte-identical across runs, but deterministic reports enable caching, reproducible tests,
and easier agent debugging. The in-tree reference helper writes zip entries with a pinned timestamp so identical inputs
produce identical zip bytes.

## Relationship To Bundles

Reports consume episode bundles, but report outputs are not currently included in the episode bundle. Chained reports or
bundle inclusion of prior supporting-role outputs are future work.

## See Also

- [Reporter role](../roles/REPORTER.md) for invocation.
- [Event log](EVENT_LOG.md) for structured report entries.
- [Episode bundle](EPISODE_BUNDLE.md) for reporter input.
