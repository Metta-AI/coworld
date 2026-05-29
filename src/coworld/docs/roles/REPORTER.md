# Reporter Role

**Status:** contract defined, runtime pending

## What it does

The reporter role compresses sparse episode experience into dense highlight signals — narrative summaries, news-caster
reports, interesting-moment cutdowns, structured statistics, and machine-readable event logs. Reporter runs are
on-demand: they are triggered by a CLI command or a platform action, not by the episode runner itself.

## Where it lives in the manifest

`manifest.reporter[]`, with `type: "reporter"` on every entry. The array must contain at least one runnable; Coworlds
without a custom reporter may reference `ghcr.io/metta-ai/reporters-default:latest`. See
[`COWORLD_MANIFEST.md`](../COWORLD_MANIFEST.md) for the full runnable shape.

## Contract

A reporter runnable is a short-lived, process-style container started by a CLI or platform action that wants a
per-episode report. It does not expose HTTP routes or websockets; it reads its inputs from env-var URIs, writes its
output zip, and exits.

### Input

A reporter receives one env var:

- `COGAME_EPISODE_BUNDLE_URI` — URI of the episode bundle the reporter consumes; see
  [`artifacts/EPISODE_BUNDLE.md`](../artifacts/EPISODE_BUNDLE.md).

### Output

A reporter writes its output to one env var:

- `COGAME_REPORT_URI` — URI where the reporter writes its [report artifact](../artifacts/REPORT.md).

Reports may include an [event log](../artifacts/EVENT_LOG.md) for structured tick-aligned events.

### Execution

Reporters are on-demand. They are **not** run automatically by the episode runner; an episode finishes and produces
artifacts whether or not any reporter ever runs against them.

A reporter run is triggered by a CLI command (planned: `coworld run-reporter` — exact shape TBD), a hosted button, or an
automatic Column pipeline. The invoker is responsible for:

1. Choosing which reporter to run (one of the runnables in `manifest.reporter[]`).
2. Assembling the input bundle via the bundling layer.
3. Setting `COGAME_EPISODE_BUNDLE_URI` and `COGAME_REPORT_URI` on the reporter container.
4. Waiting for the container to exit and consuming the output zip.

### Determinism

Reporters are **not required** to produce byte-identical output across runs over identical inputs, but should do so when
feasible; see [REPORT.md](../artifacts/REPORT.md#determinism).

## How it fits with other roles

Reporters live in the post-episode artifact layer. They consume the episode bundle and emit
[reports](../artifacts/REPORT.md) that feed humans, Observatory surfaces, and downstream supporting runnables. See
[`README.md`](../README.md) for the full artifact flow.

The paintarena example reporters (`paint_arena_summarizer.py`, `stats_reporter.py`) run on the canonical
`COGAME_EPISODE_BUNDLE_URI` / `COGAME_REPORT_URI` contract and write an in-zip `manifest.json` flagging their `render` /
`event_log` outputs. They are the in-tree reference implementations of the contract; the richer production reporters
live in [`Metta-AI/reporters`](https://github.com/Metta-AI/reporters).

## Future directions

The following are deliberately out of scope for v1; they are listed so future contributors know they have been
considered but deferred until a real use case lands.

- **Default renderer.** A Coworld manifest could mark one reporter as its "default renderer." Observatory would then
  automatically run that reporter against every episode and render its `render` output alongside the episode page. Not
  implemented in v1; the manifest-level marker is not yet defined.
- **Chained reports.** A reporter could consume another reporter's output as part of its input (e.g. a news-caster built
  on top of a stats-parquet reporter). The current bundle contract does not surface prior reporter outputs; chaining
  will be added when a real chained reporter ships.

## See Also

- [`artifacts/EPISODE_BUNDLE.md`](../artifacts/EPISODE_BUNDLE.md) — episode bundle consumed by this role.
- [`artifacts/REPORT.md`](../artifacts/REPORT.md) — output zip produced by this role.
- [`artifacts/EVENT_LOG.md`](../artifacts/EVENT_LOG.md) — optional structured event log inside a report.
- [`COWORLD_MANIFEST.md`](../COWORLD_MANIFEST.md) — manifest guide and generated-schema pointer.
- [`README.md`](../README.md) — role status framework, runnable conventions, and artifact flow.
- [`GRADER.md`](GRADER.md), [`DIAGNOSER.md`](DIAGNOSER.md), [`OPTIMIZER.md`](OPTIMIZER.md) — sibling supporting
  runnables that may consume reporter output.
- [`GAME.md`](GAME.md), [`PLAYER.md`](PLAYER.md) — the in-flight roles whose output reporters consume.
