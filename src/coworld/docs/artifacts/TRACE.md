# Run Trace

> **Reporter v2 (spec 0061).** This page describes the host-written run trace that replaces the
> former reporter-defined trace zip entry. The trace is a platform artifact, not a reporter
> output: the reporter cannot forge, skip, or edit it. See the
> [Reporter role](../roles/REPORTER.md).

A **trace** is the complete, machine-readable record of what a reporter run did: every tool call
it made, what the calls cost, how long they took, and the guest's own log annotations. It is
produced by the platform host as a side effect of the capability architecture — the guest's only
doorway to the world is the tool belt, and the trace recorder sits on that doorway.

Traces are **Bureau-run-only**. An external (self-hosted) reporter runs outside the platform: its
output submissions carry no run and therefore no trace — the platform can vouch for *who* said it
(the reporter key) but not *how it was made*.

## Location and shape

One JSON Lines file, `trace.jsonl`, stored beside (not among) the run's
[output parts](REPORT.md). One record per event, ordered by `seq`:

```json
{"seq":0,  "t_ms":0,     "kind":"lifecycle", "event":"run_started", "reporter_version":"rv_…", "subject":{"kind":"round","id":"round_…"}}
{"seq":14, "t_ms":4210,  "kind":"tool_call", "tool":"episodes.results", "args":{"ereq":"ereq_…"},
           "ok":true, "result_digest":"sha256:c01a…", "result_bytes":18234, "duration_ms":142}
{"seq":15, "t_ms":4480,  "kind":"tool_call", "tool":"llm.converse",
           "args_digest":"sha256:9f2c…", "args_preview":{"model":"claude-sonnet-5","input_tokens":1892},
           "ok":true, "usage":{"input_tokens":1892,"output_tokens":412,"cost_usd":0.0113}, "duration_ms":2840}
{"seq":16, "t_ms":7391,  "kind":"tool_call", "tool":"llm.converse", "ok":false,
           "error":{"kind":"bedrock_throttled","code":"ThrottlingException"}, "duration_ms":310}
{"seq":17, "t_ms":8020,  "kind":"annotation", "level":"info", "msg":"drafting recap for division A"}
{"seq":88, "t_ms":83102, "kind":"lifecycle", "event":"run_finished", "ok":true,
           "totals":{"tool_calls":74,"llm_cost_usd":0.61,"llm_errors":1,"bytes_read":48211003,"guest_wall_ms":9120}}
```

Record kinds:

| Kind | Producer | Contents |
| --- | --- | --- |
| `lifecycle` | host | `run_started` / `run_finished` with subject, reporter version, and usage totals |
| `tool_call` | host | Tool name, args (size-capped preview + digest), result digest/bytes, duration, `ok`/error kind. Data-tool calls (`episodes`, `platform`, `reports`) are authenticated HTTP requests to the public v2 API under the run-scoped token — the trace records the platform's side of those calls; `llm` calls are host-signed Bedrock requests and add tokens, Bedrock-priced cost, and latency |
| `annotation` | guest (`output.log`) | Free-form log lines, interleaved by time but marked guest-originated |

Arguments and results are **digested** with size-capped previews — the trace records what
happened, not full payloads. A per-run `debug=true` flag (requester/team only) captures full LLM
request/response bodies. `/scratch` filesystem I/O is deliberately not
traced: it is guest-internal working state, not an external effect.

## Visibility

**Requester + platform team only.** A run reads platform data under the requester's permissions,
so its trace can carry information the reporter's author has no right to see — the author is
deliberately excluded. Authors debug by requesting runs themselves, which makes them the
requester. Tracing is a debugging and audit surface, not a product surface.

## See Also

- [Report outputs](REPORT.md) for the parts the trace sits beside.
- [Reporter role](../roles/REPORTER.md) for the tool belt whose calls the trace records.
- [Event log](EVENT_LOG.md) — unrelated fixed-schema Parquet *output part*; the trace is about
  the run, the event log is about the episodes.
