# Episode annotations

Annotations are optional policy diagnostics stored separately from the replay, logs, and artifact ZIP. They explain
decisions, intents, predictions, or skill usage. The replay renderer does not consume them yet.

Write UTF-8 JSON Lines: one event per line, including a final newline. The typed envelope is
[`EpisodeAnnotation`](../../annotations.py); `args` and additional fields can contain game-specific JSON.

```json
{"schema_version":1,"time":123,"kind":"skill","function":"useSkill","args":{"skill":"dash"}}
{"schema_version":1,"time":456,"kind":"intent","function":"selectTarget","args":{"from":"Y","to":"Z"}}
```

`time` uses the game's existing timing convention. Producers and replay consumers must agree on that convention. The
platform does not translate ticks or impose a clock. Optional `end_time` describes an interval; `message` provides an
explanation, and `actor` identifies an entity controlled by the policy.

Files are capped at 64 MiB, with 16 KiB per record. Invalid or oversized hosted outputs are rejected, never truncated.
Rejection notices appear at the start of the affected policy’s downloadable log. Ordinary logs keep their existing
limits. Do not include credentials in annotations.

## Producing a file

For a game-hosted episode, `player_seats.json` supplies an optional `annotations_uri` per seat. The game's policy
runtime can append events directly to that file, keeping each seat separate. Flush and close these files before writing
`results.json`, alongside existing logs and artifacts. The runner validates and uploads them in its existing output
collection. Missing or empty files are ignored. Policies need a runtime binding to emit events; supplying a destination
alone cannot add a language-level annotation API.

Polyworld supplies `ANNOTATE(time, kind, function, args)` through its shared policy host, independently of LLM support.
Invalid input, annotation limits, and output failures return status codes without disabling the policy VM. Each seat
uses one buffered file handle, like policy logs, flushed and closed during existing episode cleanup. Desktop and WASM
hosts expose the same API and return disabled without a destination. See
[Polyworld's annotation contract](https://github.com/Metta-AI/polyworld/blob/main/coworld/integration.md#policy-annotations)
for registration, status codes, buffering, and host coverage.

The event schema, storage layout, and read API can also serve future platform-hosted producers. This implementation
collects game-hosted files. There is no new completion handshake, log parser, or annotation service. Uploads retain
existing optional-output failure behavior: teardown or crashes before publication can lose annotations, and collection
failures appear in worker logs.

## Reading annotations

```bash
coworld episode-annotations ereq_... POLICY_VERSION_UUID --output annotations.jsonl
```

The client also exposes `get_episode_request_policy_annotations`. Access requires episode visibility and policy
ownership; delegated player credentials are additionally restricted to their player. Explicit team elevation follows
existing artifact access. Friend sharing is not implemented. Storage upload capabilities do not grant read access to
other policies.

Storage keeps one object per execution attempt and policy seat. The download groups all seats of the requested policy
version into one file. It overwrites any producer-supplied `participant_slot` and `seq` with trusted position and
sequence. Order is seat order, then emission order; consumers can sort by game time. Invalid stored positions are
skipped with a server warning; a download with no valid events returns 404. The combined download has the same 64 MiB
cap. This read-time grouping needs no completion phase or storage migration.

Player-authored advice can later reuse the event envelope, but needs separate author identity, storage, and
authorization. It must not be treated as a policy's self-reported intent.
