"""Test suite for stats_reporter (canonical contract).

Covers the pure ``rows_from_episode`` projection plus the end-to-end zip
build (manifest.json + stats.parquet) and a synthetic-bundle round-trip
through ``run()``.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import pytest

from coworld.examples.paintarena.reporter import stats_reporter

_PINNED_MTIME = (1980, 1, 1, 0, 0, 0)


def test_stats_reporter_builds_replay_stats_rows() -> None:
    replay = stats_reporter.PaintArenaReplay.model_validate(
        {
            "frames": [
                {
                    "tick": 1,
                    "width": 2,
                    "height": 2,
                    "positions": [[0, 0], [1, 0]],
                    "tile_owners": [0, 1, -1, -1],
                    "scores": [1, 1],
                }
            ]
        }
    )
    results = stats_reporter.PaintArenaResults.model_validate(
        {"scores": [1.0, 1.0], "painted_tiles": [1, 1], "ticks": 1}
    )

    rows = stats_reporter.rows_from_episode(replay, results)

    assert [row.ts for row in rows] == [1] * 12
    assert [row.player for row in rows] == [-1, -1, -1, 0, 0, 1, 1, -1, 0, 0, 1, 1]
    assert [row.key for row in rows] == [
        "scores",
        "tile_owners",
        "arena",
        "position",
        "score",
        "position",
        "score",
        "final_results",
        "final_score",
        "painted_tiles",
        "final_score",
        "painted_tiles",
    ]
    assert json.loads(rows[0].value) == [1, 1]
    assert json.loads(rows[-1].value) == 1


def _make_replay_dict() -> dict[str, Any]:
    return {
        "frames": [
            {
                "tick": 1,
                "width": 2,
                "height": 2,
                "positions": [[0, 0], [1, 0]],
                "tile_owners": [0, 1, -1, -1],
                "scores": [1, 1],
            }
        ]
    }


def _make_results_dict() -> dict[str, Any]:
    return {"scores": [1.0, 1.0], "painted_tiles": [1, 1], "ticks": 1}


def _make_bundle_bytes(
    *,
    replay: dict[str, Any] | None = None,
    results: dict[str, Any] | None = None,
    ereq_id: str = "ereq_test_stats",
    status: str = "success",
) -> bytes:
    replay_payload = replay if replay is not None else _make_replay_dict()
    results_payload = results if results is not None else _make_results_dict()
    manifest = {
        "ereq_id": ereq_id,
        "status": status,
        "include": ["results", "replay"],
        "files": {"results": "results.json", "replay": "replay"},
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("results.json", json.dumps(results_payload))
        zf.writestr("replay", json.dumps(replay_payload))
    return buf.getvalue()


def _extract(payload: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        return {info.filename: zf.read(info.filename) for info in zf.infolist()}


def test_build_zip_bytes_packs_manifest_and_parquet() -> None:
    """The output zip carries an in-zip manifest.json flagging
    ``stats.parquet`` as the event_log, plus the parquet payload itself."""
    replay = stats_reporter.PaintArenaReplay.model_validate(_make_replay_dict())
    results = stats_reporter.PaintArenaResults.model_validate(_make_results_dict())

    payload = stats_reporter.build_zip_bytes(replay, results)
    files = _extract(payload)

    assert set(files.keys()) == {"manifest.json", "stats.parquet"}
    manifest = json.loads(files["manifest.json"])
    assert manifest["reporter_id"] == "paint-arena-parquet-stats-reporter"
    assert manifest["event_log"] == "stats.parquet"
    assert manifest["render"] is None
    assert manifest["trace"] is None


def test_build_zip_parquet_uses_canonical_event_log_schema() -> None:
    """The parquet payload must use the shared (ts: int64, player: int64,
    key: string, value: string) schema."""
    replay = stats_reporter.PaintArenaReplay.model_validate(_make_replay_dict())
    results = stats_reporter.PaintArenaResults.model_validate(_make_results_dict())

    payload = stats_reporter.build_zip_bytes(replay, results)
    parquet_bytes = _extract(payload)["stats.parquet"]
    table = pq.read_table(io.BytesIO(parquet_bytes))

    schema = table.schema
    assert schema.field("ts").type == "int64"
    assert schema.field("player").type == "int64"
    assert schema.field("key").type == "string"
    assert schema.field("value").type == "string"


def test_build_zip_entries_have_pinned_mtime() -> None:
    """Every entry pins date_time to (1980,1,1,0,0,0) for byte-identical reruns."""
    replay = stats_reporter.PaintArenaReplay.model_validate(_make_replay_dict())
    results = stats_reporter.PaintArenaResults.model_validate(_make_results_dict())

    payload = stats_reporter.build_zip_bytes(replay, results)
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        for info in zf.infolist():
            assert info.date_time == _PINNED_MTIME


def test_run_happy_path_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end: a synthetic bundle in, a canonical report zip out."""
    bundle_path = tmp_path / "bundle.zip"
    bundle_path.write_bytes(_make_bundle_bytes())
    out_path = tmp_path / "report.zip"
    monkeypatch.setenv("COGAME_EPISODE_BUNDLE_URI", bundle_path.as_uri())
    monkeypatch.setenv("COGAME_REPORT_URI", out_path.as_uri())

    stats_reporter.run(stats_reporter.load_reporter_inputs())

    payload = out_path.read_bytes()
    files = _extract(payload)
    assert set(files.keys()) == {"manifest.json", "stats.parquet"}


def test_run_failed_bundle_status_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bundle_path = tmp_path / "bundle.zip"
    bundle_path.write_bytes(_make_bundle_bytes(status="failed"))
    out_path = tmp_path / "report.zip"
    monkeypatch.setenv("COGAME_EPISODE_BUNDLE_URI", bundle_path.as_uri())
    monkeypatch.setenv("COGAME_REPORT_URI", out_path.as_uri())

    with pytest.raises(RuntimeError, match="failed"):
        stats_reporter.run(stats_reporter.load_reporter_inputs())
    assert not out_path.exists()
