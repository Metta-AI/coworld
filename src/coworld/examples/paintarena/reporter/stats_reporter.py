"""PaintArena parquet stats reporter (reference / canonical contract).

Reads episode inputs carried by ``COGAME_REPORT_REQUEST``,
projects PaintArena replay frames plus final results into the canonical
``(ts, player, key, value)`` event-log Parquet schema (see
``docs/roles/REPORTER.md``), and writes a single ``.zip`` to the request's
``report_uri`` containing the Parquet plus a top-level
``manifest.json`` flagging the Parquet via the ``event_log`` field.

This is the "rich data" sibling of ``paint_arena_summarizer``: where the
summarizer produces a human-readable Markdown render, this reporter
produces a structured event log that downstream consumers (Observatory
event explorers, diagnosers, optimizers) can ingest columnarly.

Shared primitives (``BundleReader``, ``ReporterInputs``,
``write_events_parquet``, the output ``manifest.json`` writer) live in
the vendored ``reporter_sdk`` at ``coworld.examples.paintarena.reporter._sdk_vendored``.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from typing import Any, Self

from pydantic import BaseModel, model_validator

from coworld.examples.paintarena.reporter._sdk_vendored import (
    BundleReader,
    OutputManifest,
    ReporterInputs,
    build_report_zip,
    load_reporter_inputs,
    write_events_parquet,
    write_uri,
)

# The reporter's self-identifying id, stamped into the output zip's
# ``manifest.json`` ``reporter_id`` field. Matches the runnable's ``id``
# in ``manifest.reporter[]``.
REPORTER_ID = "paint-arena-parquet-stats-reporter"


class PaintArenaFrame(BaseModel):
    tick: int
    width: int
    height: int
    positions: list[list[int]]
    tile_owners: list[int]
    scores: list[int]

    @model_validator(mode="after")
    def _positions_match_scores(self) -> Self:
        if len(self.positions) != len(self.scores):
            raise ValueError(
                f"Frame at tick {self.tick}: positions length {len(self.positions)} != scores length {len(self.scores)}"
            )
        return self


class PaintArenaReplay(BaseModel):
    frames: list[PaintArenaFrame]


class PaintArenaResults(BaseModel):
    scores: list[float]
    painted_tiles: list[int]
    ticks: int

    @model_validator(mode="after")
    def _painted_tiles_match_scores(self) -> Self:
        if len(self.painted_tiles) != len(self.scores):
            raise ValueError(f"painted_tiles length {len(self.painted_tiles)} != scores length {len(self.scores)}")
        return self


@dataclass(frozen=True)
class ParquetRow:
    ts: int
    player: int
    key: str
    value: str


def rows_from_episode(replay: PaintArenaReplay, results: PaintArenaResults) -> list[ParquetRow]:
    rows: list[ParquetRow] = []

    for frame in replay.frames:
        rows.append(_row(frame.tick, -1, "scores", frame.scores))
        rows.append(_row(frame.tick, -1, "tile_owners", frame.tile_owners))
        rows.append(_row(frame.tick, -1, "arena", {"width": frame.width, "height": frame.height}))
        for slot, position in enumerate(frame.positions):
            rows.append(_row(frame.tick, slot, "position", position))
            rows.append(_row(frame.tick, slot, "score", frame.scores[slot]))

    rows.append(_row(results.ticks, -1, "final_results", results.model_dump(mode="json")))
    for slot, score in enumerate(results.scores):
        rows.append(_row(results.ticks, slot, "final_score", score))
        rows.append(_row(results.ticks, slot, "painted_tiles", results.painted_tiles[slot]))

    return rows


def _row(ts: int, player: int, key: str, value: Any) -> ParquetRow:
    return ParquetRow(ts=ts, player=player, key=key, value=json.dumps(value, separators=(",", ":"), sort_keys=True))


def build_zip_bytes(replay: PaintArenaReplay, results: PaintArenaResults) -> bytes:
    """Build the canonical output zip: top-level ``manifest.json`` flagging
    ``stats.parquet`` as the event log, plus the Parquet payload itself."""
    rows = rows_from_episode(replay, results)
    parquet_bytes = write_events_parquet(
        [{"ts": r.ts, "player": r.player, "key": r.key, "value": r.value} for r in rows]
    )
    return build_report_zip(
        OutputManifest(
            reporter_id=REPORTER_ID,
            event_log="stats.parquet",
        ),
        [("stats.parquet", parquet_bytes)],
    )


def run(inputs: ReporterInputs) -> None:
    rows: list[ParquetRow] = []
    for episode in inputs.episodes:
        with BundleReader(episode) as bundle:
            inner = bundle.inner_manifest()
            if inner.status != "success":
                raise RuntimeError(f"bundle status={inner.status!r}; reporter cannot operate on a failed episode")
            replay = PaintArenaReplay.model_validate(bundle.read_json("replay"))
            results = PaintArenaResults.model_validate(bundle.read_json("results"))
        rows.extend(rows_from_episode(replay, results))
    parquet_bytes = write_events_parquet(
        [{"ts": r.ts, "player": r.player, "key": r.key, "value": r.value} for r in rows]
    )
    payload = build_report_zip(
        OutputManifest(
            reporter_id=REPORTER_ID,
            event_log="stats.parquet",
        ),
        [("stats.parquet", parquet_bytes)],
    )
    write_uri(inputs.report_uri, payload, content_type="application/zip")
    print(
        f"[{REPORTER_ID}] wrote zip to {inputs.report_uri}",
        file=sys.stderr,
        flush=True,
    )


if __name__ == "__main__":
    run(load_reporter_inputs())
