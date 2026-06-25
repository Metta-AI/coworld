from __future__ import annotations

import zipfile
from collections.abc import Sequence
from io import BytesIO
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

from pydantic import BaseModel, NonNegativeInt, PositiveInt

JSON_CONTENT_TYPE = "application/json"
ZIP_CONTENT_TYPE = "application/zip"
ZIP_ENTRY_MTIME = (1980, 1, 1, 0, 0, 0)


class BundleFiles(BaseModel):
    results: str
    replay: str


class BundleManifest(BaseModel):
    files: BundleFiles


class PaintArenaResults(BaseModel):
    scores: list[float]
    painted_tiles: list[NonNegativeInt]
    ticks: NonNegativeInt


class ReplayConfig(BaseModel):
    width: PositiveInt
    height: PositiveInt


class PaintArenaReplay(BaseModel):
    config: ReplayConfig


class PaintArenaEpisode(BaseModel):
    results: PaintArenaResults
    replay: PaintArenaReplay


class PaintArenaOutcome(BaseModel):
    score: float
    margin_tiles: int
    total_tiles: int
    winner_slot: int | None
    tie: bool


def read_data(uri: str, *, user_agent: str) -> bytes:
    parsed = urlparse(uri)
    if parsed.scheme in ("http", "https"):
        request = Request(uri, headers={"User-Agent": user_agent})
        with urlopen(request, timeout=30) as response:
            return response.read()
    if parsed.scheme == "file":
        return Path(unquote(parsed.path)).read_bytes()
    if parsed.scheme == "":
        return Path(uri).read_bytes()
    raise ValueError(f"Unsupported URI for read_data: {uri}")


def write_data(uri: str, data: bytes, *, content_type: str, user_agent: str) -> None:
    parsed = urlparse(uri)
    if parsed.scheme in ("http", "https"):
        request = Request(uri, data=data, method="PUT")
        request.add_header("Content-Type", content_type)
        request.add_header("User-Agent", user_agent)
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
    raise ValueError(f"Unsupported URI for write_data: {uri}")


def model_json_bytes(model: BaseModel) -> bytes:
    return f"{model.model_dump_json(indent=2)}\n".encode("utf-8")


def deterministic_zip(entries: Sequence[tuple[str, bytes]]) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, payload in entries:
            info = zipfile.ZipInfo(filename=name, date_time=ZIP_ENTRY_MTIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, payload)
    return buffer.getvalue()


def load_paint_arena_episode(bundle_uri: str, *, user_agent: str) -> PaintArenaEpisode:
    with zipfile.ZipFile(BytesIO(read_data(bundle_uri, user_agent=user_agent))) as bundle:
        manifest = BundleManifest.model_validate_json(bundle.read("manifest.json"))
        return PaintArenaEpisode(
            results=PaintArenaResults.model_validate_json(bundle.read(manifest.files.results)),
            replay=PaintArenaReplay.model_validate_json(bundle.read(manifest.files.replay)),
        )


def paint_arena_outcome(results: PaintArenaResults, replay: PaintArenaReplay) -> PaintArenaOutcome:
    if len(results.painted_tiles) != 2:
        raise ValueError("PaintArena supporting roles expect exactly two painted_tiles counts")

    slot_0_tiles = results.painted_tiles[0]
    slot_1_tiles = results.painted_tiles[1]
    margin_tiles = abs(slot_0_tiles - slot_1_tiles)
    total_tiles = replay.config.width * replay.config.height
    winner_slot = None if slot_0_tiles == slot_1_tiles else int(slot_1_tiles > slot_0_tiles)
    return PaintArenaOutcome(
        score=round(margin_tiles / total_tiles, 4),
        margin_tiles=margin_tiles,
        total_tiles=total_tiles,
        winner_slot=winner_slot,
        tie=winner_slot is None,
    )
