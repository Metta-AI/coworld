# Report Artifact

> **Reporter integration note.** This zip is the reporter artifact envelope. Process-style reporters write it to
> the `report_uri` inside `COGAME_REPORT_REQUEST`; hosted reporter services write it to the `report_uri` supplied
> over `WEBSOCKET /reporter`. The platform MVP only requires a valid zip upload; the zip contents are reporter-defined and
> should match the reporter's declared purpose/output format. See the [Reporter role](../roles/REPORTER.md).

The **report artifact** is a reporter-written zip that explains or summarizes one completed episode.

## Producer

The [reporter role](../roles/REPORTER.md) writes one zip per report request. Process-style reporters read
`COGAME_REPORT_REQUEST` and write to the request's `report_uri`. Hosted reporter services receive `report_uri` over
`/reporter`, consume the requested direct
episode artifact refs, decide which episode evidence matters, and write a report for humans, UIs, agents, or downstream
supporting roles.

## Zip Contents

A report zip may contain Markdown, HTML, JSON, Parquet, images, or other reporter-owned files. It may include a
top-level `manifest.json` that describes important entries:

```json
{
  "reporter_id": "paint-arena-summarizer",
  "render": "summary.md",
  "event_log": "events.parquet",
  "trace": "trace.jsonl"
}
```

Suggested fields when a reporter chooses to include `manifest.json`:

| Field | Required? | Purpose |
| --- | --- | --- |
| `reporter_id` | recommended | Reporter self-identification, conventionally matching the runnable id in `manifest.reporter[]`. |
| `render` | optional | Path inside the zip to one `.md` or `.html` file that platform UI surfaces can embed. Must follow the safe [render profile](RENDER.md); `coworld certify` rejects unsafe HTML. |
| `event_log` | optional | Path inside the zip to one `.parquet` file following the [event log](EVENT_LOG.md) schema. |
| `trace` | optional | Path inside the zip to one `.jsonl` or `.json` machine-readable trace artifact. |

All files in the zip are reporter-defined. Consumers may use reporter-provided metadata such as `manifest.json` to find
renderable, trace, and structured entries, but should not assume the platform has enforced a particular in-zip metadata
schema yet.

## Determinism

Reporters are not required to be byte-identical across runs, but deterministic reports enable caching, reproducible tests,
and easier agent debugging. The in-tree reference helper writes zip entries with a pinned timestamp so identical inputs
produce identical zip bytes.

## Relationship To Bundles

Reports consume episode artifact refs, but report outputs are not currently included in the episode bundle. Chained
reports or bundle inclusion of prior supporting-role outputs are future work.

## See Also

- [Reporter role](../roles/REPORTER.md) for invocation.
- [Render artifact](RENDER.md) for the safe embeddable `render` entry contract.
- [Event log](EVENT_LOG.md) for structured report entries.
- [Episode bundle](EPISODE_BUNDLE.md) for grader, diagnoser, and user-download inputs.
