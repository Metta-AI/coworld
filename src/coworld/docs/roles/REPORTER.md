# Reporter Role

**Status:** contract defined, runtime pending

## What it does

The reporter role compresses sparse episode experience into dense highlight signals — narrative summaries, tick-aligned
timeseries, and categorical event streams that feed humans, Observatory surfaces, and downstream supporting roles.

Unlike the per-episode bundle runner it replaces, a reporter is a **persisted service**: one container spans many
episodes and rounds. The platform wakes it over a WebSocket when there is something to report on, the reporter does
whatever work it defines, and it writes its output back over the same socket. The reporter is a black box from the
platform's perspective — the platform knows only when to wake it, what entity to wake it about, and what shape of output
to expect.

## Where it lives in the manifest

`manifest.reporter[]`, with `type: "reporter"` on every entry. The section is optional; include reporter runnables when
the Coworld ships custom reporter services. Each entry declares, in addition to the shared runnable shape (`id`, `name`,
`description`, `image`, `run`, `env`, `source_url`), two reporter-specific fields:

- **`purpose`** — what kind of signal the reporter produces. One of `narrative`, `timeseries`, or `categorical_events`
  today; the set is expected to grow.
- **`output_format`** — the shape of the payload the reporter writes back. Either a **bare MIME string** (e.g.
  `"text/markdown"`) for human-terminal outputs, or a typed **`{ "mime": ..., "schema": ... }`** descriptor whose
  `schema` is the JSON Schema a downstream machine consumer validates the payload against. The string form is the clean
  upgrade lane to a named-format registry later.

See [`COWORLD_MANIFEST.md`](../COWORLD_MANIFEST.md) for the full runnable shape and
[`coworld_manifest_schema.json`](../../coworld_manifest_schema.json) for the exact field contract.

### Manifest examples

Narrative reporter, human-terminal output:

```json
{
  "reporter": [
    {
      "id": "match-recap",
      "type": "reporter",
      "name": "Match Recap",
      "description": "Renders a Markdown recap for each completed episode.",
      "image": "my-recap-reporter:latest",
      "run": ["python", "reporter.py"],
      "purpose": "narrative",
      "output_format": "text/markdown"
    }
  ]
}
```

Timeseries reporter, machine-consumed output with a declared schema:

```json
{
  "reporter": [
    {
      "id": "territory-series",
      "type": "reporter",
      "name": "Territory Timeseries",
      "description": "Per-tick territory ownership for downstream analysis.",
      "image": "my-series-reporter:latest",
      "purpose": "timeseries",
      "output_format": {
        "mime": "application/json",
        "schema": {
          "type": "object",
          "properties": {
            "ts": { "type": "array", "items": { "type": "integer" } },
            "owned": { "type": "array", "items": { "type": "number" } }
          },
          "required": ["ts", "owned"]
        }
      }
    }
  ]
}
```

Runnable `env` values are public configuration only. Secrets and private credentials do not belong in the manifest or
container environment.

## Contract

A reporter is a long-lived container that exposes a WebSocket server, consistent with how games and commissioners
communicate. The difference from the commissioner is scope and input: a commissioner is scoped to one round and is fed
round context; a reporter spans many episodes/rounds and **fetches its own inputs over HTTPS** rather than receiving a
fixed episode bundle.

### Runtime contract

The reporter container follows the same listen-on-8080 conventions as game and commissioner containers:

- Listen on `0.0.0.0:8080`.
- Serve `GET /healthz` returning 200 when ready to accept a WebSocket connection.
- Serve `WEBSOCKET /report` — the channel over which the platform wakes the reporter and receives its output.

The platform waits for `/healthz` to return 200, then connects to `/report`. All subsequent communication happens over
that WebSocket connection as JSON messages with a `"type"` field.

### Inputs

A reporter's input is **not** a fixed episode bundle. After being woken, the reporter makes whatever HTTPS requests it
needs to gather the data it wants — episode artifacts, prior reports, external context. A reporter may still be written
to read env-var URIs (the manifest `env` block can point it at endpoints), but the contract does not mandate any
particular input env var. The `report_request` wake carries a `context` bag of optional platform hints (for example,
known artifact URIs) the reporter may use or ignore.

Because the reporter owns its own inputs, it also owns its own cross-wake state. Unlike the commissioner, the platform
does **not** carry an opaque state blob for a reporter; a reporter that needs memory across wakes persists it itself
(its own storage, fetched over HTTPS).

### Wake lifecycle

A reporter is woken on demand and may idle (or scale to zero) between wakes:

1. The platform decides a report is due for some entity (an episode completed, a round closed, a manual refresh).
2. If the reporter is not running, the platform starts it and polls `/healthz` until ready (startup timeout).
3. The platform connects to `WEBSOCKET /report` (or reuses a live connection) and sends `report_request` with the
   target entity, a reason, and any context hints.
4. The reporter optionally sends `report_accepted` to acknowledge long work, gathers what it needs over HTTPS, and does
   its work.
5. The reporter sends `report_output` — the payload, bound to the request's target, in its declared `output_format` —
   or `report_failed` if it cannot produce output.
6. The platform routes the output to the matching consumer or surface and may let the reporter idle until the next wake.
7. On deploy, idle scale-down, or shutdown, the platform sends `drain`; the reporter finishes in-flight requests and
   exits cleanly.

A single reporter service handles many `report_request` messages over its lifetime and must not assume it sees every
episode.

### Protocol message types

All reporter protocol messages are JSON objects with a `"type"` discriminator. Pydantic models are defined in
[`reporter/protocol.py`](../../reporter/protocol.py).

#### Platform → reporter

##### `report_request`

The wake. Asks the reporter to produce output for one target entity:

```json
{
  "type": "report_request",
  "request_id": "req_001",
  "target": { "kind": "episode", "id": "ereq_abc" },
  "reason": "episode_completed",
  "context": { "results_uri": "https://.../results.json" }
}
```

`target.kind` is open (`episode`, `round`, `league`, `policy_version`, …) because a reporter service spans entity types.
`context` is opaque platform hints; the reporter may fetch its own inputs instead. `request_id` is echoed on the
matching output or failure.

##### `drain`

Asks the reporter to finish in-flight work and exit cleanly (deploy, idle scale-down, shutdown):

```json
{ "type": "drain", "reason": "deploy" }
```

#### Reporter → platform

##### `report_accepted`

Optional acknowledgement that a request was received and is being worked (also serves as liveness for long work):

```json
{ "type": "report_accepted", "request_id": "req_001" }
```

##### `report_output`

The produced output, bound to the triggering request and target:

```json
{
  "type": "report_output",
  "request_id": "req_001",
  "target": { "kind": "episode", "id": "ereq_abc" },
  "mime": "text/markdown",
  "encoding": "text",
  "payload": "# Match Recap\n\nBlue held 62% of territory..."
}
```

`mime` must match the reporter's declared `output_format`. `encoding` says how the payload is carried on the wire:
`text` for a plain string, `json` for an inline JSON value validated against the declared output-format schema, `base64`
for binary bytes encoded into the `payload` string, or `binary` (below). One reporter emits one declared format; each
output is addressed to the entity that triggered the wake.

**Binary payloads.** For large binary outputs (e.g. Parquet event logs), `base64` inflates the payload ~33% and forces
the whole blob through a JSON string. Use `encoding: "binary"` instead: omit `payload` and send the bytes as the
**immediately following** WebSocket binary frame.

```json
{
  "type": "report_output",
  "request_id": "req_002",
  "target": { "kind": "episode", "id": "ereq_abc" },
  "mime": "application/vnd.apache.parquet",
  "encoding": "binary"
}
```

Because a raw binary frame carries no `request_id`, all correlation stays in this control message. A reporter **must**
send a `binary`-encoded `report_output` and its trailing binary frame back-to-back, with no other frame interleaved on
that connection between them (hold a per-connection send lock around the pair). The platform attributes the next binary
frame to the `request_id`/`target` named in the preceding `report_output`. This rule is what makes the binary carrier
safe even when the reporter has multiple requests in flight on one socket.

##### `report_failed`

The reporter could not produce output for a request:

```json
{
  "type": "report_failed",
  "request_id": "req_001",
  "target": { "kind": "episode", "id": "ereq_abc" },
  "error": "results artifact not yet available"
}
```

### Health and liveness

- **`/healthz`** — polled before the WebSocket connect (startup probe) and periodically while the reporter is up
  (liveness probe).
- **WebSocket ping/pong** — standard protocol-level pings; an unresponsive reporter is terminated.

## How it fits with other roles

Reporters live in the post-episode analysis layer. They turn episode evidence into the narrative, timeseries, and
categorical-event signals that humans and downstream roles (diagnosers, optimizers, Observatory surfaces) consume. Like
the commissioner, a reporter holds a long-lived WebSocket contract with the platform; unlike the commissioner, it is not
scoped to a round, it sources its own inputs, and it emits per-entity outputs rather than round-level decisions.

See [`README.md`](../README.md) for the full artifact and control-flow diagram.

## Implementation status

The protocol message models are live in [`reporter/protocol.py`](../../reporter/protocol.py). The platform's `/report`
WebSocket driver and the reporter-service runtime are not yet shipped, so `manifest.reporter[]` entries are declared but
not yet invoked as services. Production reporters live in [`Metta-AI/reporters`](https://github.com/Metta-AI/reporters).

### Legacy reference (superseded)

The in-tree paintarena reporters (`paint_arena_summarizer.py`, `stats_reporter.py`) and their vendored SDK implement the
**superseded** contract: a short-lived container that read `COGAME_EPISODE_BUNDLE_URI` and wrote a report zip to
`COGAME_REPORT_URI`. They are retained as a transitional reference until a WebSocket reporter-service reference lands,
and the legacy artifact contracts they produce are documented under
[`artifacts/REPORT.md`](../artifacts/REPORT.md), [`artifacts/EVENT_LOG.md`](../artifacts/EVENT_LOG.md), and
[`artifacts/TRACE.md`](../artifacts/TRACE.md), all marked legacy. Do not build new reporters against the zip contract;
build against the WebSocket service contract above.

## Future directions

- **Named-format registry.** `output_format` accepts a bare MIME string or a `{mime, schema}` descriptor today; a future
  third form can reference a registered named format so common shapes need not restate their schema inline.
- **Additional purposes.** The `purpose` set (`narrative`, `timeseries`, `categorical_events`) is expected to grow as new
  consumer surfaces appear.
- **Default renderer.** A Coworld could mark one reporter as its default renderer, which Observatory runs automatically
  and renders alongside each episode. The manifest-level marker is not yet defined.

## See Also

- [`reporter/protocol.py`](../../reporter/protocol.py) — Pydantic models for every protocol message.
- [`COMMISSIONER.md`](COMMISSIONER.md) — sibling long-lived WebSocket service; the closest contract analog.
- [`COWORLD_MANIFEST.md`](../COWORLD_MANIFEST.md) — manifest guide and generated-schema pointer.
- [`artifacts/EPISODE_BUNDLE.md`](../artifacts/EPISODE_BUNDLE.md) — episode evidence a reporter may fetch over HTTPS.
- [`artifacts/REPORT.md`](../artifacts/REPORT.md), [`artifacts/EVENT_LOG.md`](../artifacts/EVENT_LOG.md),
  [`artifacts/TRACE.md`](../artifacts/TRACE.md) — the legacy zip output contracts (superseded).
- [`README.md`](../README.md) — role status framework, runnable conventions, and artifact flow.
- [`GRADER.md`](GRADER.md), [`DIAGNOSER.md`](DIAGNOSER.md), [`OPTIMIZER.md`](OPTIMIZER.md) — sibling supporting
  runnables that may consume reporter output.
- [`GAME.md`](GAME.md), [`PLAYER.md`](PLAYER.md) — the in-flight roles whose output reporters analyze.
