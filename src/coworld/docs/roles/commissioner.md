# Commissioner Role

**Status:** contract defined, runtime pending

## What it does

The commissioner role decides the structure of a league: which episodes get scheduled in each round, which policy
versions play in each episode and in which slots, and how policies move between divisions based on results.
Commissioners run once per league round — they are scoped to a single round, not a single episode.

The canonical contract is documented in
[spec 0044, Custom Commissioner API](../../../../../../docs/specs/0044-custom-commissioner-api.md). Today the
platform's commissioners (e.g. `AmongThemCommissioner` for the Among Them Daily league) implement this protocol
in-process; the container WebSocket runtime that lets game authors ship custom commissioner images is not yet
wired up.

## Where it lives in the manifest

`manifest.commissioner[]`, with `type: "commissioner"` on every entry. The array must contain at least one
runnable; Coworlds without a custom commissioner may reference `softmax/default-commissioner:latest`, the
platform-provided default. See [`MANIFEST_README.md`](../../MANIFEST_README.md) for the full runnable shape.

## Contract

Unlike reporter, grader, diagnoser, and optimizer (all per-episode), the commissioner is a **per-round** runnable
that exposes a WebSocket server. Once a round begins, the platform starts the commissioner container, connects to
its `/round` WebSocket, exchanges JSON protocol messages, and lets the container exit when the round completes.

### Runtime contract

- Listen on `0.0.0.0:8080`.
- Serve `GET /healthz` returning 200 when ready to accept a WebSocket connection.
- Serve `WEBSOCKET /round` — the main communication channel for the round.

### Round lifecycle

1. Platform decides a new round is due (per the league's scheduling config).
2. Platform starts the commissioner container.
3. Platform polls `/healthz` until ready (startup timeout configurable).
4. Platform opens the `/round` WebSocket and sends `round_start` (round context: divisions, memberships, recent
   results, variants, optional state blob from the previous round).
5. Commissioner replies with `schedule_episodes` listing the episodes it wants to run; platform acks with
   `episodes_accepted` or `episodes_rejected`.
6. As scheduled episodes complete, platform sends `episode_result` (or `episode_failed`).
7. Commissioner may schedule more episodes or declare the round done.
8. Commissioner sends `round_complete` (per-division rankings, graduation changes, optional state blob) and exits.
9. Platform records results, applies graduation changes, persists state for the next round.

If the platform needs to cancel the round mid-stream, it sends `round_abort`. The commissioner is expected to
exit cleanly without sending `round_complete` in that case.

### Protocol message types

All commissioner protocol messages are JSON objects with a `"type"` discriminator. Pydantic models are defined in
[`commissioner/protocol.py`](../../commissioner/protocol.py); the full message reference lives in
[spec 0044](../../../../../../docs/specs/0044-custom-commissioner-api.md).

Platform → commissioner:

- `round_start` — round context sent once at the beginning.
- `episodes_accepted` / `episodes_rejected` — acks for the commissioner's `schedule_episodes` requests.
- `episode_result` / `episode_failed` — per-episode outcomes streamed as episodes complete.
- `round_abort` — platform-initiated round cancellation.

Commissioner → platform:

- `schedule_episodes` — request a batch of episodes (variant id + ordered per-slot policy version ids).
- `round_complete` — final per-division rankings, graduation changes, optional opaque state blob.

### State persistence

The `round_complete` message carries an optional `state` JSON blob (max 10 MB) that the platform stores and
passes back to the commissioner in the next round's `round_start`. This lets a commissioner maintain ratings,
bracket progress, swiss pairings, etc. across rounds without external storage. The blob is opaque to the platform.

### Health and liveness

The platform monitors commissioner health via `/healthz` and standard WebSocket ping/pong. Failure to respond to
a ping within the configured timeout, or a non-200 from `/healthz`, terminates the container and fails the round.

## How it fits with other roles

The commissioner sits at the top of the league control loop. It tells the platform which episodes to run; the
platform's game runner dispatches those episodes (with the requested policy versions in the requested slots); the
game runnable produces episode results; the platform routes those results back to the commissioner as
`episode_result` messages; and the commissioner eventually closes the round with rankings.

Unlike reporter, grader, diagnoser, and optimizer — all of which consume *individual* episode artifacts on demand
after episodes finish — the commissioner consumes a stream of episode results in aggregate during a round and
emits round-level decisions. It is the only supporting role besides game that holds a long-lived WebSocket
contract with the platform.

See [`OVERVIEW.md`](OVERVIEW.md) for the full artifact and control-flow diagram.

## Current implementation status

The protocol message models are live in [`commissioner/protocol.py`](../../commissioner/protocol.py). The
platform's existing commissioners (notably `AmongThemCommissioner` for the Among Them Daily league) speak this
protocol in-process — they implement the same `schedule_episodes` / `round_complete` shape directly in Python
rather than going over a WebSocket. See
[`AMONGTHEM_COMMISSIONER.md`](../../../../../../app_backend/src/metta/app_backend/v2/AMONGTHEM_COMMISSIONER.md)
for the in-process reference.

What's still pending:

- The platform-side WebSocket `/round` driver (the code that starts a commissioner container, polls `/healthz`,
  opens the WebSocket, and pumps the protocol). Not yet shipped.
- The `softmax/default-commissioner:latest` reference image. Not yet built.

Until both land, `manifest.commissioner[]` entries are declared but not actually invoked as containers; Coworld
leagues run through the in-process Python commissioners on the backend.

## See Also

- [spec 0044, Custom Commissioner API](../../../../../../docs/specs/0044-custom-commissioner-api.md) — full
  protocol reference, default-commissioner CLI flags, scheduling config, RBAC, migration path.
- [`commissioner/protocol.py`](../../commissioner/protocol.py) — Pydantic models for every protocol message.
- [`AMONGTHEM_COMMISSIONER.md`](../../../../../../app_backend/src/metta/app_backend/v2/AMONGTHEM_COMMISSIONER.md) —
  in-process AmongThem commissioner reference (backend doc).
- [`MANIFEST_README.md`](../../MANIFEST_README.md) — manifest field reference for `manifest.commissioner[]`.
- [`COWORLD_README.md`](../../COWORLD_README.md) — Role Status framework, runnable conventions.
- [`reporter.md`](reporter.md), [`grader.md`](grader.md), [`diagnoser.md`](diagnoser.md), [`optimizer.md`](optimizer.md) — sibling supporting runnables; all per-episode.
- [`OVERVIEW.md`](OVERVIEW.md) — full artifact and control-flow diagram.
