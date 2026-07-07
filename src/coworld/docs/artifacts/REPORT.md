# Report Outputs

> **Reporter v2 (spec 0061).** This page describes the typed output-part contract that replaces
> the former report-zip envelope. There is no zip: a report is a set of individually stored,
> individually addressable parts, declared before any run exists. See the
> [Reporter role](../roles/REPORTER.md).

A **report** is a set of typed **output parts** a reporter produces. Each part is declared at
registration — name, catalog type, and a natural-language `description` of what the part means —
and every produced part arrives through **one outputs API**, `POST /v2/reporters/outputs`, which
validates it against the declaration server-side and stores it as a row in the
`reporter_outputs` table pointing at its own object with a canonical encoding.

The API accepts two credentials, one per hosting mode:

- **Run context** — a Bureau run's `output.emit(name, value)` tool call; the row carries the run
  id, and parts are unique per `(run, name)`.
- **Reporter key** — an external (self-hosted) reporter's direct `POST`; the row has no run
  (`reporter_run_id NULL`), and the reporter's output history is append-only.

Both paths hit identical per-type validation; consumers see one kind of part regardless of which
door it came through.

## The output catalog

Part types are platform-defined and versioned with the `softmax:reporter` world. V1 launches with
exactly five; the catalog extends only when a real need arrives (additions are additive releases).

| Part type | Payload | Canonical storage | Notes |
| --- | --- | --- | --- |
| `render-html` | self-contained HTML string | `.html`, `text/html` | Must pass the safe [render profile](RENDER.md) at submission time; inline assets as `data:` URIs. Platform UI surfaces embed this part. |
| `render-markdown` | Markdown string | `.md`, `text/markdown` | |
| `event-log` | list of events | `.parquet` | The fixed 4-column [event log](EVENT_LOG.md) schema (`ts, player, key, value`); the host writes the Parquet with pinned deterministic settings. |
| `json` | JSON string | `.json`, `application/json` | Validated against the schema URI declared for that part. |
| `file` | media-type + bytes | raw object | The escape hatch for anything else. A reporter needing "a directory of stuff" emits multiple named `file` parts — still enumerated, described, and typed at the envelope level. |

## Submission semantics

- A submission with an undeclared name, a mismatched type, unsafe HTML, an invalid JSON payload,
  or a size overrun returns a **typed error, synchronously** — to the guest inside a Bureau run,
  as the HTTP response for an external `POST`. Validation is part of submission, not a post-hoc
  check.
- Run completion requires every declared part to have been emitted, unless the part is declared
  `optional`. (External reporters have no runs and no completion gate — each submission stands
  alone.)
- Within a Bureau run, emitting the same name twice replaces the earlier value — rows are unique
  on `(run, name)`. External submissions never replace; the history is append-only.
- Bureau output is bounded by the run's output budget (256 MiB default); per-part size caps apply
  identically to both paths.

## Consumption

Parts are queryable by run or by reporter: a completed run exposes a **part listing** — name,
type, description, size, content hash, URL — and an external reporter exposes its submission
history newest-first via `GET /v2/reporters/{id}/outputs`; any single part streams with its
canonical content type via `GET /v2/reporters/outputs/{output_id}`. The same listings are what
the `reports` tool hands to a chained reporter, so downstream reporters know what each upstream
part *means* before fetching it. Because parts are separate rows and objects, consumers fetch
exactly what they need: the UI embeds the `render-html` part without touching a replay-sized
`file` part next to it.

Beside a Bureau run's parts (not among them) sits the run's [trace](TRACE.md) — the platform's
audit record, with different producers and access rules than the reporter's own outputs. External
submissions have no trace.

## Determinism

Reporters are not required to be byte-identical across runs, but deterministic parts enable
caching, reproducible tests, and easier agent debugging. Host-written encodings (`event-log`
Parquet) are deterministic by construction.

## Relationship To Bundles

Reporters read episode evidence through the `episodes` tool (backed by the same per-episode
artifacts the [episode bundle](EPISODE_BUNDLE.md) packages for graders, diagnosers, and
downloads). Report parts are not included in episode bundles; chained reporters read them through
the `reports` tool instead.

## See Also

- [Reporter role](../roles/REPORTER.md) for the declaration and run contract.
- [Render artifact](RENDER.md) for the safe `render-html` profile.
- [Event log](EVENT_LOG.md) for the `event-log` part schema.
- [Trace](TRACE.md) for the host-written run trace beside the outputs.
