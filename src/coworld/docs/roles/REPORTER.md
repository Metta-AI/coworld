# Reporter Role

**Status:** MVP hosted runner

## What it does

The reporter role compresses sparse episode experience into dense review surfaces — narrative summaries, tick-aligned
time series, categorical event streams, traces, visualizations, and other outputs that make an episode legible to humans,
Observatory surfaces, diagnosers, optimizers, and coding agents.

Reporters are for "what happened?" Graders are for "how valuable or interesting was it?" Keeping that boundary sharp
matters: reporters expose evidence; graders decide which evidence should drive ranking, learning, or attention.

## Where it lives in the manifest

`manifest.reporter[]`, with `type: "reporter"` on every entry. The section is optional; include reporter runnables when
the Coworld has custom reporter containers or a default reporter is useful.

The current enforced manifest schema uses the shared runnable shape for reporters: `id`, `type`, `name`, `description`,
`image`, optional `run`, optional public `env`, optional `source_url`, and optional `repository_url`. Do **not** add
reporter-only manifest fields yet; the current schema rejects extra fields.

The reporter design vocabulary still expects each reporter to have two explicit concepts:

- **Purpose** — what kind of signal the reporter produces. Current names are `narrative`, `timeseries`, and
  `categorical_events`; the set is expected to grow.
- **Output format** — the shape of the reporter's output. Human-terminal outputs should name a MIME type such as
  `text/markdown`; machine-consumed outputs should pair a MIME type with a schema so downstream tools can parse the
  content without out-of-band knowledge. Reporter services write a zip artifact; the declared output format describes
  the primary content inside that zip, not the transport container itself.

Until those concepts become schema fields, put them in the reporter's manifest `description`, implementation README, and
report-output metadata. See [`COWORLD_MANIFEST.md`](../COWORLD_MANIFEST.md) for the full current manifest shape and
[`coworld_manifest_schema.json`](../../coworld_manifest_schema.json) for the exact enforced contract.

### Manifest Example

```json
{
  "reporter": [
    {
      "id": "match-recap",
      "type": "reporter",
      "name": "Match Recap",
      "description": "Purpose: narrative. Output: text/markdown episode recap.",
      "image": "my-recap-reporter:latest",
      "run": ["python", "reporter.py"]
    }
  ]
}
```

## Contract

A reporter's hosted runtime contract is a service container that the platform starts for a reporter run. The platform
connects when there is something to report on, sends direct episode artifact refs and an output URI, the reporter writes a
report zip to that URI, and the reporter sends lifecycle messages over the WebSocket. The MVP runner uses one
Kubernetes reporter service per reporter run and cleans it up after the request finishes.

The Crewrift lab reporter implements this hosted shape as an external reference, while the in-tree Paint Arena reporters
use the same request shape through the local process contract documented below.

### Hosted Service Contract

The hosted reporter service mirrors the game and commissioner container conventions:

- Listen on `0.0.0.0:8080`.
- Serve `GET /healthz`, returning 200 when ready.
- Serve `WEBSOCKET /reporter`, the control channel over which the runner requests a report and receives lifecycle
  messages.

The reporter is single-request-per-connection for v1. A runner connects, receives readiness, sends one report request,
waits for completion or failure, and then the reporter closes the connection.

Hosted reporters must finish before the platform deadline. The current hosted runner defaults to a six-hour maximum
reporter lifetime and issues input/output presigned URLs with an eight-hour TTL.

Reports may include an [event log](../artifacts/EVENT_LOG.md) for structured tick-aligned events and a
[trace](../artifacts/TRACE.md) for richer reporter-defined machine timelines. A report's optional `render` entry — the
file platform UI surfaces can embed — must follow the safe [render profile](../artifacts/RENDER.md) so it is safe to
embed even though the reporter is author-supplied.

### Wake Lifecycle

1. The platform decides a report is due for an entity: an episode completed, a round closed, or a manual refresh was
   requested.
2. If the reporter container is not running, the platform starts it and waits for `/healthz`.
3. The platform opens `WEBSOCKET /reporter`.
4. The reporter accepts the socket and sends `reporter_ready`.
5. The platform sends `report_request` with `request_id`, `report_uri`, and `episodes`.
6. The reporter sends `report_started`, reads the requested artifact refs, builds the report, and writes a `.zip` to `report_uri`.
7. The reporter sends `report_finished` with the `report_uri` and summary counts, or `report_failed` with a stage and
   error.
8. The reporter closes the WebSocket.

### Hosted Protocol Messages

All hosted protocol messages are JSON objects with a `type` discriminator. The episode-input models are mirrored in the
Paint Arena vendored reporter SDK and in the backend reporter runner.

Platform to reporter:

- `report_request`: asks the reporter to produce one report zip.

Reporter to platform:

- `reporter_ready`: sent immediately after WebSocket accept.
- `report_started`: acknowledgement that the request validated and work began.
- `report_progress`: optional progress update for long work.
- `report_finished`: report zip was written to `report_uri`.
- `report_failed`: structured failure for one request.

Minimal request:

```json
{
  "type": "report_request",
  "request_id": "req_001",
  "report_uri": "https://.../round-report.zip",
  "episodes": [
    {
      "episode_request_id": "ereq_abc",
      "status": "success",
      "manifest": {
        "ereq_id": "ereq_abc",
        "status": "success",
        "include": ["results", "replay", "game_logs"],
        "files": {
          "results": "results.json",
          "replay": "replay",
          "game_logs": {
            "combined": "logs/game.log"
          }
        }
      },
      "artifacts": {
        "results": {
          "uri": "https://.../jobs/job_123/results.json",
          "media_type": "application/json",
          "encoding": "identity"
        },
        "replay": {
          "uri": "https://.../jobs/job_123/replay.z",
          "media_type": "application/octet-stream",
          "encoding": "zlib"
        },
        "game_logs": {
          "combined": {
            "uri": "https://.../jobs/job_123/logs.txt",
            "media_type": "text/plain",
            "encoding": "identity"
          }
        }
      },
      "inline_json": {}
    }
  ]
}
```

Each `episodes[]` entry carries the bundle-style manifest plus direct artifact refs. The platform presigns source
artifacts in the eval artifact store; it does not assemble or upload an input zip. `replay` refs are zlib-compressed in
hosted storage and declare `"encoding": "zlib"` so SDK readers can decompress on demand. Small synthesized JSON payloads
such as `error_info` travel under `inline_json` instead of being uploaded as separate artifacts.

Reporter messages:

```json
{ "type": "reporter_ready", "protocol_version": "coworld-reporter/v1" }
```

```json
{ "type": "report_started", "request_id": "req_001", "episode_count": 2 }
```

```json
{
  "type": "report_progress",
  "request_id": "req_001",
  "stage": "reading_bundles",
  "completed": 1,
  "total": 2
}
```

```json
{
  "type": "report_finished",
  "request_id": "req_001",
  "report_uri": "https://.../round-report.zip",
  "episode_count": 2,
  "players": 8
}
```

```json
{
  "type": "report_failed",
  "request_id": "req_001",
  "stage": "rendering",
  "error": "RuntimeError: ..."
}
```

### Report Zip Output

The reporter writes `application/zip` bytes to `report_uri`. The zip is the artifact envelope; the reporter's
`output_format` describes the primary content inside the envelope. For example:

- A `text/html` narrative reporter writes a zip containing an `.html` entry.
- A `text/markdown` narrative reporter writes a zip containing a `.md` entry.
- A machine-consumed JSON reporter writes a zip containing a JSON entry that validates against the reporter's declared
  schema.
- A time-series or categorical-event reporter may write Parquet, JSONL, or JSON entries.

MVP platform orchestration only requires the reporter to upload a valid zip. Reporters may include a top-level
`manifest.json` or any other metadata file to help downstream consumers find primary renderable, structured, or trace
entries, but the platform does not require that file yet.

### Local Process Contract

The currently shipped Paint Arena reporters are short-lived process containers:

- Input: `COGAME_REPORT_REQUEST`, containing the same `report_request` JSON shape as the hosted protocol.
- Output: the `report_uri` inside that request, where the reporter writes a [report zip](../artifacts/REPORT.md).

Local certification uses `file://` artifact refs in that request. Hosted orchestration uses presigned `https://` refs.

### Certification

`coworld certify` exercises the local process contract end-to-end. After the certification episode produces results and
a replay, it builds a one-episode `COGAME_REPORT_REQUEST` with `file://` refs and runs **every** runnable in
`manifest.reporter[]` against it. Each report zip is then validated: its `manifest.json` must parse, every declared
`render` / `event_log` / `trace` entry must exist with an accepted extension, and an HTML `render` entry must satisfy the
safe [render profile](../artifacts/RENDER.md). A reporter that crashes, writes no report, or emits an unsafe render entry
fails certification. A Coworld with no reporters certifies unchanged.

### Determinism

Reporters are not required to produce byte-identical output across runs over identical inputs, but should do so when
feasible. Deterministic outputs enable caching, reproducible tests, and easier agent debugging.

## How it fits with other roles

Reporters live in the post-episode analysis layer. They turn episode evidence into narrative, time-series, categorical
event, trace, or visualization signals that humans and downstream roles consume. The optimizer is the center of gravity:
reporters are one of its sensory organs, alongside graders and diagnosers.

The paintarena example reporters (`paint_arena_summarizer.py`, `stats_reporter.py`) run on the
`COGAME_REPORT_REQUEST` process contract and write an in-zip `manifest.json` flagging their `render` / `event_log`
outputs. That manifest is reporter-owned metadata, not a platform requirement. Richer production reporters live in
[`Metta-AI/coworld-tools/reporters`](https://github.com/Metta-AI/coworld-tools/tree/main/reporters).

## Future directions

The following are deliberately out of scope for v1; they are listed so future contributors know they have been
considered but deferred until a real use case lands.

- **Schema-level purpose/output format.** The manifest should eventually carry reporter `purpose` and `output_format`
  fields directly. That is not enforced today.
- **Named-format registry.** A future `output_format` form can reference a named format so common machine-readable shapes
  do not restate their schema inline.
- **Default renderer.** A Coworld manifest could mark one reporter as its default renderer. Observatory would then run
  that reporter and render its output alongside the episode page. The manifest-level marker is not yet defined.
- **Chained reports.** A reporter could consume another reporter's output as part of its input. Chaining will be added
  when a real chained reporter ships.

## See Also

- [`artifacts/EPISODE_BUNDLE.md`](../artifacts/EPISODE_BUNDLE.md) — episode bundle consumed by graders, diagnosers, and
  user-facing downloads.
- [`artifacts/REPORT.md`](../artifacts/REPORT.md) — report zip produced by process reporters and hosted reporter services.
- [`artifacts/EVENT_LOG.md`](../artifacts/EVENT_LOG.md) — optional structured event log inside a report zip.
- [`artifacts/TRACE.md`](../artifacts/TRACE.md) — optional machine-readable trace inside a report zip.
- [`COWORLD_MANIFEST.md`](../COWORLD_MANIFEST.md) — manifest guide and generated-schema pointer.
- [`README.md`](../README.md) — role status framework, runnable conventions, and artifact flow.
- [`GRADER.md`](GRADER.md), [`DIAGNOSER.md`](DIAGNOSER.md), [`OPTIMIZER.md`](OPTIMIZER.md) — sibling supporting
  runnables that may consume reporter output.
- [`GAME.md`](GAME.md), [`PLAYER.md`](PLAYER.md) — the in-flight roles whose output reporters consume.
