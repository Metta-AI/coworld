# Events Artifact

> **Log Contract v1 (optional).** `events.json` is the game-authored envelope the default platform Log
> (`docs/surfaces/logs.md`, at the monorepo root) reads to raise itself from tier 0 to tier 1. It is not required, it is
> not schema-validated, and an unrecognized shape never fails an episode, a certify run, or the default Log — the
> platform Log simply renders tier 0 (results + metadata only) when `events.json` is absent or does not look like the
> envelope below.

The **events artifact** is an optional, game-written JSON (or NDJSON) stream of per-tick analysis events, written as the
game plays.

## Producer

The [game role](../roles/GAME.md) may write events during rollout mode, one record per interesting tick-aligned fact:

- local runner: `events.json` in the artifact workspace;
- hosted runner: bytes uploaded to `EVENTS_URI`;
- game container input: `COGAME_EVENTS_URI`.

Unlike [results](RESULTS.md) and [replay](REPLAY.md), `events.json` is deliberately not derived after the episode ends —
the game writes it incrementally, tick by tick, as events occur. A Coworld that never emits any events simply never
writes the file; the upload step skips it, and nothing downstream treats that as an error.

## Envelope

`events.json` is either a single JSON array or newline-delimited JSON (NDJSON), where each record is an object:

```json
{ "tick": 1042, "kind": "capture", "agent": 3, "team": "red", "x": 12, "y": 4 }
```

| Field    | Type          | Required | Purpose                                                                                                                               |
| -------- | ------------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| `tick`   | int           | yes      | Episode tick when the event occurred.                                                                                                 |
| `kind`   | string        | yes      | Event name, e.g. `"attack"`, `"capture"`, `"death"`. Free-form; the game defines its own vocabulary.                                  |
| `agent`  | int or string | no       | The agent or player slot this event is about, when it is agent-scoped.                                                                |
| `team`   | string        | no       | The team this event is about, when the game has teams.                                                                                |
| `x`, `y` | number        | no       | Position on the game's grid or map, when the event has a location.                                                                    |
| ...      | any           | no       | Any other game-specific fields. The envelope is intentionally open — extra keys are preserved but not interpreted by the default Log. |

There is no `results_schema`-style validation for `events.json`: it is optional and unschematized by design (matching
the universal per-episode contract's existing treatment of this file). A record missing `tick` or `kind`, a malformed
line in an NDJSON stream, or a file that is not valid JSON at all is simply not recognized as the envelope — the default
Log falls back to tier 0 rather than failing.

## Size guidance

`events.json` shares the platform's general per-artifact size discipline: keep it proportional to episode length, not to
total game state. A few hundred bytes per tick (one or two events with a handful of scalar fields) keeps a
multi-thousand-tick episode well under a few megabytes. Emit one record per notable occurrence, not one record per tick
regardless of activity — a heatmap or timeline reads the same whether ticks with no events are represented by absence or
are omitted entirely, so omitting them is both smaller and simpler.

## What the default Log renders (tier 1)

When `events.json` is present and at least one record matches the envelope above, the platform's default Log
(`softmax/episode-log`, see `docs/surfaces/logs.md` at the monorepo root) adds, beside its tier 0 results/metadata
panels:

- a **kind counts** table — how many events of each `kind` occurred;
- a **tick timeline** — events binned by tick, so activity over the episode's duration is visible at a glance;
- **per-agent counts** — event counts grouped by `agent`, when the field is present;
- a **heatmap** — plotted from `x`/`y` when both are present on at least some records (no arena backdrop is drawn; the
  manifest has no concept of arena geometry to draw one against).

None of this is required. A Coworld that never writes `events.json` still gets a complete tier 0 Log from
`results.json`, replay, and game-log alone.

## Consumers

- The default platform Log reporter (tier 1), as described above.
- A game's own bespoke reporter (spec 0061), which may read `events.json` through the same `episodes` tool other
  artifacts use, for its own analysis or presentation.

## Relationship to the reporter `event-log` output

`events.json` is a different thing from the reporter [event log](EVENT_LOG.md) output part: this artifact is
game-written, optional, unschematized JSON/NDJSON consumed by the default platform Log, while
[`EVENT_LOG.md`](EVENT_LOG.md) is a _reporter-produced_ Parquet output with a fixed 4-column schema (`ts`, `player`,
`key`, `value`) emitted through the reporter `output` tool (spec 0061).

## Contract

- Format: JSON array or NDJSON of objects, each with `tick` (int) and `kind` (string), plus any optional fields.
- Validation: none. Unrecognized shapes are never a failure.
- Local filename: `events.json`.
- Hosted artifact: `EVENTS_URI`, uploaded as `application/json`.
- Game container input: `COGAME_EVENTS_URI`.
- Optional: absence is a normal outcome, not an error.

## See Also

- [Game role](../roles/GAME.md) for the producer contract.
- [Results](RESULTS.md) for the required, schema-validated companion artifact.
- [Event log](EVENT_LOG.md) for the reporter-produced Parquet output this artifact is not.
- `docs/surfaces/logs.md` for the default Log's tier ladder and the Log Contract v1 hints that build on this artifact.
