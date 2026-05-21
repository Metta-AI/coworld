from __future__ import annotations

import gzip
import json
import os
import zlib
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any, Self
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

from pydantic import BaseModel, model_validator

HTTP_USER_AGENT = "coworld-paintarena-stats-reporter/0.1"
PARQUET_CONTENT_TYPE = "application/vnd.apache.parquet"


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


def read_data(uri: str) -> bytes:
    parsed = urlparse(uri)
    if parsed.scheme in ("http", "https"):
        request = Request(uri, headers={"User-Agent": HTTP_USER_AGENT})
        with urlopen(request, timeout=30) as response:
            return response.read()
    if parsed.scheme == "file":
        return Path(unquote(parsed.path)).read_bytes()
    if parsed.scheme == "":
        return Path(uri).read_bytes()
    raise ValueError(f"Unsupported URI for read_data: {uri}")


def post_data(uri: str, data: bytes) -> None:
    parsed = urlparse(uri)
    if parsed.scheme in ("http", "https"):
        request = Request(uri, data=data, method="POST")
        request.add_header("Content-Type", PARQUET_CONTENT_TYPE)
        request.add_header("User-Agent", HTTP_USER_AGENT)
        with urlopen(request, timeout=60):
            return
    if parsed.scheme == "file":
        path = Path(unquote(parsed.path))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return
    if parsed.scheme == "":
        path = Path(uri)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return
    raise ValueError(f"Unsupported URI for post_data: {uri}")


def load_json_artifact(uri: str) -> Any:
    data = read_data(uri)
    artifact_path = urlparse(uri).path
    if artifact_path.endswith(".json.z"):
        data = zlib.decompress(data)
    elif artifact_path.endswith(".json.gz"):
        data = gzip.decompress(data)
    return json.loads(data)


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


def write_parquet(uri: str, rows: list[ParquetRow]) -> None:
    pa: Any = import_module("pyarrow")
    pq: Any = import_module("pyarrow.parquet")

    table = pa.table(
        {
            "ts": [row.ts for row in rows],
            "player": [row.player for row in rows],
            "key": [row.key for row in rows],
            "value": [row.value for row in rows],
        },
        schema=pa.schema(
            [
                ("ts", pa.int64()),
                ("player", pa.int64()),
                ("key", pa.string()),
                ("value", pa.string()),
            ]
        ),
    )
    sink = pa.BufferOutputStream()
    pq.write_table(table, sink)
    post_data(uri, sink.getvalue().to_pybytes())


def main() -> None:
    replay = PaintArenaReplay.model_validate(load_json_artifact(os.environ["COGAME_REPLAY_URI"]))
    results = PaintArenaResults.model_validate(load_json_artifact(os.environ["COGAME_RESULTS_URI"]))
    write_parquet(os.environ["COGAME_REPLAY_STATS_PARQUET_URI"], rows_from_episode(replay, results))


if __name__ == "__main__":
    main()
