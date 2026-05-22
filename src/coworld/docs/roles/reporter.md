# Reporter Role

**Status:** contract defined, runtime pending

## What it does

The reporter role compresses sparse episode experience into dense highlight signals — narrative summaries,
news-caster reports, interesting-moment cutdowns, structured statistics, and machine-readable event logs. Reporter
runs are on-demand: they are triggered by a CLI command or a platform action, not by the episode runner itself.

## Where it lives in the manifest

`manifest.reporter[]`, with `type: "reporter"` on every entry. The array must contain at least one runnable;
Coworlds without a custom reporter may reference `softmax/default-reporter:latest`. See
[`MANIFEST_README.md`](../../MANIFEST_README.md) for the full runnable shape.

## Contract

A reporter runnable is a short-lived, process-style container started by a CLI or platform action that wants a
per-episode report. It does not expose HTTP routes or websockets; it reads its inputs from env-var URIs, writes its
output zip, and exits.

### Input

A reporter receives one env var:

- `COGAME_EPISODE_BUNDLE_URI` — URI (file:// locally, https:// hosted) of a `.zip` file containing the episode's
  artifacts. The reporter reads the zip, inspects its `manifest.json` to discover what's inside, and processes the
  files it cares about. See [`EPISODE_BUNDLE_README.md`](../../EPISODE_BUNDLE_README.md) for the full bundle
  contract.

A reporter input bundle always contains `results.json` and `replay.json`; it may also contain `config.json`, game
logs, per-player logs (subject to access control), and `error_info.json` if the episode failed.

### Output

A reporter writes its output to one env var:

- `COGAME_REPORT_URI` — URI (file:// locally, https:// or s3:// hosted) where the reporter writes a single `.zip`
  containing all report files.

The output zip may include any files the reporter needs (Markdown, HTML, parquet, images, JSON, etc.). At the root
of the zip, the reporter should include a `manifest.json` describing the contents:

```json
{
  "reporter_id": "paint-arena-summarizer",
  "render": "summary.md",
  "event_log": "stats.parquet"
}
```

| Field         | Required?   | Purpose                                                                |
| ------------- | ----------- | ---------------------------------------------------------------------- |
| `reporter_id` | recommended | The id this reporter self-reports for itself. Conventionally matches the runnable's `id` in `manifest.reporter[]`, but the platform does not enforce a match. Useful for caches and downstream consumers tracking provenance. |
| `render`      | optional    | Path inside the zip to a single `.md` or `.html` file that UIs should render. At most one per output. |
| `event_log`   | optional    | Path inside the zip to a single Parquet file containing structured tick-aligned events. At most one per output. See [Event log schema](#event-log-schema) below. |

All other files in the zip are free-form; reporters can include any auxiliary assets their output needs.

#### Event log schema

When a reporter writes an `event_log` parquet file, it must use the following column schema:

| Column   | Type   | Purpose                                                                        |
| -------- | ------ | ------------------------------------------------------------------------------ |
| `ts`     | int64  | Episode tick at which the event occurred.                                       |
| `player` | int64  | Player slot (0..N-1) for player-scoped events, or `-1` for global events.       |
| `key`    | string | Event name or stat key.                                                          |
| `value`  | string | Event value. JSON-encoded if the value is structured.                            |

The event log is the primary structured-data surface that downstream diagnosers and optimizers consume. It is the
mechanism by which a reporter ties events and stat changes of interest to the specific ticks at which they
occurred — so a diagnoser can ground "your policy did X at tick Y" in concrete evidence, and an optimizer can
correlate ticks with reward signals and policy decisions.

### Execution

Reporters are on-demand. They are **not** run automatically by the episode runner; an episode finishes and produces
artifacts whether or not any reporter ever runs against them.

A reporter run is triggered by a CLI command (planned: `coworld run-reporter` — exact shape TBD), a hosted button,
or an automatic Column pipeline. The invoker is responsible for:

1. Choosing which reporter to run (one of the runnables in `manifest.reporter[]`).
2. Assembling the input bundle via the bundling layer.
3. Setting `COGAME_EPISODE_BUNDLE_URI` and `COGAME_REPORT_URI` on the reporter container.
4. Waiting for the container to exit and consuming the output zip.

### Determinism

Reporters are **not required** to produce byte-identical output across runs over identical inputs, but should do so
when feasible. Deterministic reporters enable caching and reproducible testing. The paintarena summarizer is an
existing example of a deterministic reporter; LLM-based or otherwise non-deterministic reporters are also valid.

## How it fits with other roles

Reporters live in the post-episode artifact layer. They consume episode bundles assembled on demand from the game
runnable's per-URI outputs, and emit human-readable summaries (`render`) and structured event logs (`event_log`)
that feed humans, Observatory surfaces, and downstream supporting runnables. The `event_log` parquet specifically
is the structured data path that diagnosers and optimizers read to tie agent and game events to ticks. See
[`OVERVIEW.md`](OVERVIEW.md) for the full artifact flow.

The paintarena example reporters (`paint_arena_summarizer.py`, `stats_reporter.py`) were written against an earlier
contract (per-artifact env vars) and will be migrated to the `COGAME_EPISODE_BUNDLE_URI` / `COGAME_REPORT_URI`
shape; migration is tracked separately.

## Future directions

The following are deliberately out of scope for v1; they are listed so future contributors know they have been
considered but deferred until a real use case lands.

- **Default renderer.** A Coworld manifest could mark one reporter as its "default renderer." Observatory would
  then automatically run that reporter against every episode and render its `render` output alongside the episode
  page. Not implemented in v1; the manifest-level marker is not yet defined.
- **Chained reports.** A reporter could consume another reporter's output as part of its input (e.g. a news-caster
  built on top of a stats-parquet reporter). The current bundle contract does not surface prior reporter outputs;
  chaining will be added when a real chained reporter ships.

## See Also

- [`EPISODE_BUNDLE_README.md`](../../EPISODE_BUNDLE_README.md) — full bundle contract the reporter consumes.
- [`MANIFEST_README.md`](../../MANIFEST_README.md) — manifest field reference for `manifest.reporter[]`.
- [`COWORLD_README.md`](../../COWORLD_README.md) — Role Status framework, runnable conventions.
- [`grader.md`](grader.md), [`diagnoser.md`](diagnoser.md), [`optimizer.md`](optimizer.md) — sibling supporting
  runnables that may consume reporter output.
- [`game.md`](game.md), [`player.md`](player.md) — the in-flight roles whose output reporters consume.
- [`OVERVIEW.md`](OVERVIEW.md) — full artifact flow.
