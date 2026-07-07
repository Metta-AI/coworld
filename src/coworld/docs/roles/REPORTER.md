# Reporter Role

**Status:** Reporter v2 (spec 0061) — Wasm reporters. This is the reporter contract; the
container/WebSocket reporter path it replaced has been deleted.

## What it does

The reporter role compresses sparse episode experience into dense review surfaces — narrative
summaries, tick-aligned time series, categorical event streams, visualizations, and other outputs
that make platform activity legible to humans, Observatory surfaces, diagnosers, optimizers, and
coding agents.

Reporters are for "what happened?" Graders are for "how valuable or interesting was it?" Keeping
that boundary sharp matters: reporters expose evidence; graders decide which evidence should drive
ranking, learning, or attention.

## The shape of a reporter

A reporter is a **registered platform identity** — first-class like a player policy, not a coworld
appendage. Registration (`POST /v2/reporters/register`) is the front door: it takes a name, a
description, and the declared outputs contract, and returns the permanent identity plus a
**reporter key**.

- **Named and owned.** A reporter's name is unique **per owner**, not globally — many people can
  have a `round-recap`. The human-readable handle is `owner/name` (names cannot contain `/`); the
  `rptr_` id is the unambiguous identity.
- **Keyed.** The reporter key is a static secret, shown once at registration and rotatable via
  `POST /v2/reporters/{id}/key/rotate`; the platform stores only its sha256 hash. Its sole power
  is **submitting outputs as that reporter** — proof of authorship, not a data credential. A
  leaked key forges bylines, nothing more; rotate and move on.
- **Hosted either way, one identity.** Ask the platform to host a compiled wasm component (the
  Bureau runs it — below), or host the reporter yourself: run it anywhere and `POST` outputs with
  your key. Consumers see one kind of reporter and one kind of output.

### Platform-hosted: the wasm component

A platform-hosted reporter is a **WebAssembly component** uploaded against the registered
identity:

- **Immutably versioned.** Each upload creates an immutable, content-addressed **version**
  (identical bytes + attributes dedupe to the same version). Uploading a new name registers the
  reporter and issues its key — upload *is* registration for the hosted path.
- **Written in your language.** Compile to a component targeting the published
  `softmax:reporter` WIT world — the authoritative interface definition (exported `run`, the
  `types`/`episodes`/`platform`/`reports`/`llm`/`output` tool interfaces, and the `tool-error`
  variant) lives at
  [`packages/coworld/src/coworld/wit/softmax-reporter/world.wit`](../../wit/softmax-reporter/world.wit).
  Toolchains: Python via `componentize-py`, JavaScript/TypeScript via `jco`, Rust via
  `cargo-component`, Go via TinyGo. SDKs wrap the raw WIT imports in idiomatic APIs — Python
  first, JavaScript second; Rust/Go target the WIT directly.
- **Capability-scoped.** The component exports one function, `run(request)`, and imports only the
  platform tool belt plus minimal WASI (clocks, random, and a private `/scratch` filesystem). No
  sockets, no environment, no ambient anything. If a reporter can do something, it is because a
  tool exists for it — and every tool call is metered, budgeted, and recorded in the run's trace.
- **Size-capped at 200 MB.** Generous headroom: Python components (bundled CPython) run
  30–60 MB; JS ~10–20 MB; Rust a few MB.

### Self-hosted (external)

An external reporter skips the wasm entirely: register, then run your program anywhere — a cron
box, a notebook, someone else's cloud. When it has something to say, `POST /v2/reporters/outputs`
with the `X-Reporter-Key: <reporter key>` header, the part `name` and `type` (and `media_type` for
`file` parts) as query parameters, and the part payload as the **raw request body**. The server
validates name+type against your declared outputs and runs the per-type content check (safe-HTML
for `render-html`, JSON well-formedness for `json`, the fixed Parquet schema for `event-log`). The
submission passes the same per-type validation as a Bureau emission, lands in the same
`reporter_outputs` table, and is served by the same routes — it simply has no run attached and
**no trace** (see [TRACE.md](../artifacts/TRACE.md)).
You read platform data with your own normal user credentials; the key is only for submitting. The
platform's involvement begins and ends at the outputs API — no sandbox, no queue, no limits
beyond output validation and size caps.

### Declared outputs

Every registration declares the outputs the reporter emits — each with a name, a type from the
platform **output catalog**, and a natural-language `description` of what that output means.
External submissions validate against this same contract; hosted versions additionally declare
the sandbox limits they need:

```json
{
  "purpose": "narrative",
  "world": "softmax:reporter@0.1.0",
  "outputs": [
    { "name": "recap",  "type": "render-html",
      "description": "A broadcast-style narrative recap of the round: standings movement, notable plays, one headline per division." },
    { "name": "events", "type": "event-log",
      "description": "Tick-aligned scoring and elimination events for every episode in the subject round." },
    { "name": "stats",  "type": "json", "schema": "https://example.com/recap-stats.schema.json",
      "description": "Per-player aggregates backing the recap: points, survival time, head-to-head records." }
  ],
  "requested_limits": { "memory_mib": 1024, "llm_usd": 5.00 }
}
```

Consumers — UI surfaces, chained reporters, agents deciding which part to read — know the shape
*and meaning* of a report before a single run exists. See
[REPORT.md](../artifacts/REPORT.md) for the output catalog and part contract.

### Requested limits

Sandbox limits are defaults with per-version overrides: the upload's `requested_limits` asks, the
platform records `granted_limits` (v1: automatic approval within hard ceilings). Defaults: 512 MiB
memory, 120 s guest CPU, 15 min wall clock, 1 GiB `/scratch`, 2 000 tool calls, $2.00 LLM spend,
2 GiB artifact reads, 256 MiB total output.

## Where it lives in the manifest

Reporters are no longer bundled in coworld manifests — the manifest's optional `reporter[]`
section holds **references**:

```json
{
  "reporter": [
    { "reporter": "acme/match-recap@3" },
    { "wasm": "./reporters/recap.wasm",
      "id": "recap",
      "attributes": { "purpose": "narrative", "outputs": [ … ] } }
  ]
}
```

- A **platform reference** (`"reporter": "owner/name@version"`) points at an existing submitted
  reporter version. References are owner-qualified because reporter names are only unique per
  owner.
- A **wasm reference** points at a component your coworld build produces; `coworld publish`
  submits it through the standard upload flow, auto-creating (or extending) a reporter named
  `{coworld-name}-{id}` owned by you (reporter names cannot contain `/` — it is the owner
  separator in handles). Republishing unchanged bytes+attributes dedupes to the existing version.

The section is optional. There are **no default reporters** — nothing is injected, and a coworld
with no reporters certifies unchanged.

## The run contract

Runs exist only for platform-hosted reporters — an external reporter has no runs, just output
submissions. The platform (the Bureau, its capability-scoped runtime) instantiates your component
per run — in milliseconds; there is no cold start to design around — and calls:

```
run(request: run-request) -> result<run-summary, string>
```

`run-request` carries the run id, the **subject** (a list of episode-request ids, a round, a
league, a player, or `freeform`), and optional opaque JSON `params`. Your program then works the
tool belt until it has emitted its declared outputs:

The data tools are thin clients of the **public platform API** — every `episodes`, `platform`,
and `reports` call is an authenticated HTTP request to the same `/v2` routes any user could hit,
presenting a short-lived run-scoped token. Only `llm` talks to a non-API backend.

| Tool family | What it gives you |
| --- | --- |
| `episodes` | Episode artifacts by episode-request id: results, replay, game logs, per-player logs, error info — typed sugar over the public episode routes |
| `platform` | `get(path, query)` over an allowlisted subset of public platform read APIs: leagues, rounds, standings, players, coworlds, experience requests |
| `reports` | Other reporters' outputs, addressed by run id or by reporter id + part name — typed, described part listings and fetches over the outputs routes (chained reports, including external reporters' outputs) |
| `llm` | Bedrock models (`converse`/`invoke`) — host-signed, metered against your run's budget, billed to the run's requester |
| `output` | `emit(name, part-value)` for each declared output — submitted through the same outputs API external reporters use, authenticated by the run context; `progress(pct, note)`; `log(level, msg)` |

Key semantics:

- **You see with the requester's eyes.** At dispatch the platform mints a run-scoped token
  carrying the run requester's (or subscription owner's) principal, snapshotted at enqueue; every
  data read presents it, so the API enforces exactly that user's row-level visibility.
- **`/scratch` is yours.** A private, empty, per-run filesystem (1 GiB default) for temp files —
  ordinary `open()` works. It is destroyed at run end and never traced.
- **Emit is validated synchronously, server-side.** Each emission lands as a row in the
  `reporter_outputs` table via the outputs API; undeclared names, type mismatches, unsafe HTML,
  or size overruns come back as typed errors you can react to, inside the run. External
  submissions pass the identical validation.
- **Budget exhaustion is a typed error**, not a kill: you may still emit partial declared outputs.
- **Everything is traced.** The host records every tool call (digests, timings, LLM tokens/cost)
  into the run's [trace](../artifacts/TRACE.md). The trace is visible to the run's requester and
  the platform team — not to you as the author, unless you are the requester. Debug by running
  your reporter yourself.

## How reporters get run

Uploading never causes execution. Runs come only from explicit bindings:

- **On-demand** — anyone requests a run of any reporter over a subject via the platform API/CLI.
- **Attached to an experience request** — opt-in: an XP request may name reporter versions to run
  over its episodes when they finish.
- **Subscriptions** — a standing binding: run this reporter on `round_closed`,
  `episode_completed`, or `cron` within a scope (league/coworld). Anyone may subscribe a reporter
  to any league — the subscriber pays for the runs.

Whoever causes a run pays for it (LLM spend included); the reporter author never does. External
reporters are outside this machinery entirely — you run them on your own schedule, at your own
cost, and only the output submissions touch the platform.

## Certification

Submission performs **static validation**, and `coworld certify` runs the same validator against
every manifest reference: the component parses, targets a supported world version, imports nothing
outside the world and the WASI 0.2 surface, exports `run`, declares well-formed outputs, and
requests limits within ceilings. (Guest toolchains link the whole WASI surface, sockets included —
isolation comes from the runtime, which never grants network authority, so every socket operation
traps.) Behavioral
certification (smoke runs against golden episodes, output conformance) is deferred to the unified
certification effort.

## Determinism

Reporters are not required to produce byte-identical output across runs over identical inputs, but
should when feasible (LLM-driven reporters naturally will not be). Deterministic outputs enable
caching, reproducible tests, and easier agent debugging.

## How it fits with other roles

Reporters live in the post-episode analysis layer. They turn episode evidence into narrative,
time-series, categorical-event, or visualization signals that humans and downstream roles consume.
The optimizer is the center of gravity: reporters are one of its sensory organs, alongside graders
and diagnosers. Chained reports — a reporter consuming another reporter's typed outputs via the
`reports` tool — are first-class in v2.

## Future directions

Deliberately deferred until a real need lands:

- **WASI 0.3 world** — native async and `stream<u8>` results (replay streaming, LLM streaming).
  Worlds are versioned and accepted side by side, so this is an additive release.
- **Output catalog extensions** — `render-bundle` (multi-file HTML), `timeseries`, WIT-valued
  machine parts. Additions are catalog version bumps.
- **Certification-in-depth** — smoke runs, output conformance, behavioral checks.
- **Broadening the reporter key to data reads** — single-credential headless external reporters.
  Additive (key auth is its own branch in the outputs route) but needs a permission model first;
  today external reporters read with their operator's normal user auth.
- **Live reporting** over in-progress entities — out of scope; frequent scheduled runs cover the
  near-term need.

## See Also

- [`artifacts/REPORT.md`](../artifacts/REPORT.md) — typed output parts and the output catalog.
- [`artifacts/TRACE.md`](../artifacts/TRACE.md) — the host-written run trace.
- [`artifacts/EVENT_LOG.md`](../artifacts/EVENT_LOG.md) — the fixed Parquet schema behind the
  `event-log` part type.
- [`artifacts/RENDER.md`](../artifacts/RENDER.md) — the safe render profile behind `render-html`.
- [`COWORLD_MANIFEST.md`](../COWORLD_MANIFEST.md) — manifest guide, including reporter references.
- [`README.md`](../README.md) — role status framework and artifact flow.
- [`GRADER.md`](GRADER.md), [`DIAGNOSER.md`](DIAGNOSER.md), [`OPTIMIZER.md`](OPTIMIZER.md) —
  sibling roles that may consume reporter output.
- [`GAME.md`](GAME.md), [`PLAYER.md`](PLAYER.md) — the in-flight roles whose output reporters
  consume.
