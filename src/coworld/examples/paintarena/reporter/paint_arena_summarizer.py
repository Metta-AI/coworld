"""PaintArena summarizer reporter.

Pure function of (results JSON, episode metadata JSON, replay JSON) that
produces a zip containing a Markdown summary and a JSON stats blob, per the
D12 zip + `render.txt` contract. See DESIGN.md for the full specification.
Grid dimensions come from the game-owned replay's `config` (per the reporter
contract D11); PaintArena's replay format is defined by its game server in
coworld.

The inline primitives in this file (ReporterInputs, read_uri/write_uri) are
SDK extraction candidates -- once a second reporter exists, they'll be lifted
into reporter_sdk and this file will import them instead.
"""

from __future__ import annotations

import io
import json
import os
import sys
import time
import urllib.parse
import zipfile
from pathlib import Path
from typing import Any

import requests
from pydantic import BaseModel, NonNegativeInt

# ---------- inline primitives (SDK extraction candidates) ----------


class ReporterInputs(BaseModel):
    results_uri: str
    replay_uri: str
    episode_metadata_uri: str
    report_output_uri: str
    reporter_id: str


def load_reporter_inputs() -> ReporterInputs:
    return ReporterInputs(
        results_uri=os.environ["COGAME_RESULTS_URI"],
        replay_uri=os.environ["COGAME_REPLAY_URI"],
        episode_metadata_uri=os.environ["COGAME_EPISODE_METADATA_URI"],
        report_output_uri=os.environ["COGAME_REPORT_OUTPUT_URI"],
        reporter_id=os.environ["COGAME_REPORTER_ID"],
    )


_HTTP_RETRY_STATUSES = {429, 500, 502, 503, 504}
_HTTP_MAX_ATTEMPTS = 5


def _file_path_from_uri(uri: str) -> Path:
    parsed = urllib.parse.urlparse(uri)
    return Path(urllib.parse.unquote(parsed.path))


def read_uri(uri: str) -> bytes:
    scheme = urllib.parse.urlparse(uri).scheme.lower()
    if scheme == "file":
        return _file_path_from_uri(uri).read_bytes()
    if scheme in ("http", "https"):
        return _http_request_with_retry("GET", uri).content
    raise ValueError(f"unsupported URI scheme {scheme!r} for read: {uri}")


def write_uri(uri: str, payload: bytes, content_type: str) -> None:
    scheme = urllib.parse.urlparse(uri).scheme.lower()
    if scheme == "file":
        path = _file_path_from_uri(uri)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return
    if scheme in ("http", "https"):
        _http_request_with_retry("PUT", uri, data=payload, headers={"Content-Type": content_type})
        return
    raise ValueError(f"unsupported URI scheme {scheme!r} for write: {uri}")


def _http_request_with_retry(
    method: str,
    uri: str,
    *,
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> requests.Response:
    delay = 0.5
    for attempt in range(1, _HTTP_MAX_ATTEMPTS + 1):
        resp = requests.request(method, uri, data=data, headers=headers, timeout=30)
        if resp.status_code < 400:
            return resp
        if resp.status_code not in _HTTP_RETRY_STATUSES or attempt == _HTTP_MAX_ATTEMPTS:
            resp.raise_for_status()
        time.sleep(delay)
        delay = min(delay * 2, 8.0)
    raise RuntimeError("unreachable")  # loop above either returns or raises


def read_json(uri: str) -> Any:
    return json.loads(read_uri(uri).decode("utf-8"))


# Pinned zip-entry mtime for byte-identical determinism (D12). Anything other
# than a fixed value would make reruns over identical inputs differ in the
# zip's local-file headers.
_DETERMINISTIC_ZIP_MTIME = (1980, 1, 1, 0, 0, 0)


def write_deterministic_zip(entries: list[tuple[str, bytes]]) -> bytes:
    """Build a zip with pinned mtimes for byte-identical reruns (D12).

    Entry order is preserved as given. Each entry's date_time is pinned to
    _DETERMINISTIC_ZIP_MTIME so two invocations over identical inputs produce
    byte-identical output.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, payload in entries:
            info = zipfile.ZipInfo(filename=name, date_time=_DETERMINISTIC_ZIP_MTIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, payload)
    return buf.getvalue()


# ---------- PaintArena-specific input/output types ----------


class PaintArenaResults(BaseModel):
    scores: list[float]
    painted_tiles: list[NonNegativeInt]
    ticks: NonNegativeInt


class PlayerMetadata(BaseModel):
    slot: int
    policy_name: str | None = None


class EpisodeMetadata(BaseModel):
    episode_id: str | None = None
    variant_id: str
    duration_seconds: float | None = None
    players: list[PlayerMetadata] = []


class ReplayConfig(BaseModel):
    # Subset of the PaintArena replay's `config` dict that this reporter
    # consumes. Other config fields (max_ticks, tick_rate, players, ...) are
    # ignored. See packages/coworld/.../paintarena/game/server.py::_replay_payload.
    width: int
    height: int


class PaintArenaReplay(BaseModel):
    # Subset of the PaintArena replay payload. Other top-level fields
    # (player_names, frames, results) are ignored by this reporter.
    config: ReplayConfig


class SlotStats(BaseModel):
    slot: int
    policy_name: str
    painted_tiles: int
    share_pct: float


class GridStats(BaseModel):
    width: int
    height: int
    total_tiles: int


class PaintArenaStats(BaseModel):
    episode_id: str | None
    variant_id: str
    grid: GridStats
    ticks: int
    duration_seconds: float | None
    slots: list[SlotStats]
    unpainted_tiles: int
    unpainted_share_pct: float
    winner_slot: int | None
    margin_tiles: int
    tie: bool


# ---------- PaintArena-specific logic ----------


def build_stats(
    results: PaintArenaResults,
    metadata: EpisodeMetadata,
    config: ReplayConfig,
) -> PaintArenaStats:
    width = config.width
    height = config.height
    total_tiles = width * height

    policy_by_slot = {p.slot: p.policy_name for p in metadata.players if p.policy_name}
    slots = [
        SlotStats(
            slot=i,
            policy_name=policy_by_slot.get(i) or f"Slot {i}",
            painted_tiles=count,
            share_pct=round(count / total_tiles * 100.0, 2) if total_tiles > 0 else 0.0,
        )
        for i, count in enumerate(results.painted_tiles)
    ]

    total_painted = sum(results.painted_tiles)
    unpainted = max(total_tiles - total_painted, 0)
    unpainted_share = round(unpainted / total_tiles * 100.0, 2) if total_tiles > 0 else 0.0

    if total_painted == 0:
        winner_slot: int | None = None
        margin = 0
        tie = False
    else:
        max_count = max(results.painted_tiles)
        leaders = [i for i, c in enumerate(results.painted_tiles) if c == max_count]
        if len(leaders) > 1:
            winner_slot = None
            margin = 0
            tie = True
        else:
            winner_slot = leaders[0]
            others = [c for i, c in enumerate(results.painted_tiles) if i != winner_slot]
            margin = max_count - max(others) if others else max_count
            tie = False

    return PaintArenaStats(
        episode_id=metadata.episode_id,
        variant_id=metadata.variant_id,
        grid=GridStats(width=width, height=height, total_tiles=total_tiles),
        ticks=results.ticks,
        duration_seconds=metadata.duration_seconds,
        slots=slots,
        unpainted_tiles=unpainted,
        unpainted_share_pct=unpainted_share,
        winner_slot=winner_slot,
        margin_tiles=margin,
        tie=tie,
    )


def render_summary_markdown(stats: PaintArenaStats) -> str:
    grid = stats.grid
    if stats.duration_seconds is not None:
        duration = f"{stats.duration_seconds:.1f} s ({stats.ticks} ticks)"
    else:
        duration = f"{stats.ticks} ticks"

    lines = [
        f"# PaintArena \u2014 Episode {stats.episode_id or 'unknown'}",
        "",
        (
            f"**Variant:** {stats.variant_id} \u00b7 "
            f"**Grid:** {grid.width} \u00d7 {grid.height} ({grid.total_tiles} tiles) \u00b7 "
            f"**Duration:** {duration}"
        ),
        "",
        "| Slot | Policy | Tiles painted | Share |",
        "| --- | --- | --- | --- |",
    ]
    for s in stats.slots:
        lines.append(f"| {s.slot} | {s.policy_name} | {s.painted_tiles} / {grid.total_tiles} | {s.share_pct:.1f}% |")
    lines.append(
        f"| \u2014 | unpainted | {stats.unpainted_tiles} / {grid.total_tiles} | {stats.unpainted_share_pct:.1f}% |"
    )
    lines.append("")

    if stats.winner_slot is None and stats.unpainted_tiles == grid.total_tiles:
        lines.append("**Result:** no tiles were painted; no winner.")
    elif stats.tie:
        max_painted = max(s.painted_tiles for s in stats.slots)
        leaders = [s for s in stats.slots if s.painted_tiles == max_painted]
        lines.append(f"**Result:** tied at {max_painted} tiles ({', '.join(s.policy_name for s in leaders)}).")
    else:
        winner = next(s for s in stats.slots if s.slot == stats.winner_slot)
        lines.append(f"**Winner:** Slot {winner.slot} ({winner.policy_name}) by {stats.margin_tiles} tiles.")
    return "\n".join(lines) + "\n"


def build_zip_bytes(
    results: PaintArenaResults,
    metadata: EpisodeMetadata,
    replay: PaintArenaReplay,
) -> bytes:
    """Build the D12 output zip: summary.md (rendered), stats.json (download),
    render.txt (single line: `summary.md`)."""
    stats = build_stats(results, metadata, replay.config)
    summary_md = render_summary_markdown(stats).encode("utf-8")
    stats_json = (json.dumps(stats.model_dump(), indent=2) + "\n").encode("utf-8")
    render_txt = b"summary.md\n"
    return write_deterministic_zip(
        [
            ("summary.md", summary_md),
            ("stats.json", stats_json),
            ("render.txt", render_txt),
        ]
    )


# ---------- orchestration ----------


def run(inputs: ReporterInputs) -> None:
    results = PaintArenaResults.model_validate(read_json(inputs.results_uri))
    metadata = EpisodeMetadata.model_validate(read_json(inputs.episode_metadata_uri))
    replay = PaintArenaReplay.model_validate(read_json(inputs.replay_uri))
    payload = build_zip_bytes(results=results, metadata=metadata, replay=replay)
    write_uri(inputs.report_output_uri, payload, content_type="application/zip")
    print(f"[{inputs.reporter_id}] wrote zip to {inputs.report_output_uri}", file=sys.stderr, flush=True)


if __name__ == "__main__":
    run(load_reporter_inputs())
