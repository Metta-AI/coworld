"""Test suite for paint_arena_summarizer (canonical contract).

Covers pure-function zip construction (build_zip_bytes, build_stats) plus
end-to-end run() invocations against file:// bundle URIs.

Output contract (canonical Coworld reporter contract,
``docs/roles/REPORTER.md``):
- A single zip is written to COGAME_REPORT_URI.
- Top-level entries: manifest.json, summary.md, stats.json.
- The in-zip manifest.json flags ``render: "summary.md"`` and carries
  ``reporter_id: "paint-arena-summarizer"``. No event_log (markdown-only
  reference reporter).
- Every zip entry has a pinned mtime of (1980, 1, 1, 0, 0, 0) so identical
  inputs produce byte-identical zips.
"""

from __future__ import annotations

import io
import json
import zipfile
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from coworld.examples.paintarena.reporter import paint_arena_summarizer as par

# ---------- synthetic PaintArena episode fixtures ----------


def make_replay(width: int = 12, height: int = 8) -> dict[str, Any]:
    """Synthetic PaintArena replay payload.

    Shape mirrors what the PaintArena game server writes
    (packages/coworld/.../paintarena/game/server.py::_replay_payload):
    ``{config, player_names, frames, results}``. The reporter only reads
    ``config.width`` and ``config.height``; other fields are present so
    the fixture realistically exercises pydantic's extras-ignored
    behavior.
    """
    return deepcopy(
        {
            "config": {
                "width": width,
                "height": height,
                "max_ticks": 100,
                "tick_rate": 5,
                "players": [
                    {"name": "Sweep Painter 1"},
                    {"name": "Sweep Painter 2"},
                ],
            },
            "player_names": ["Sweep Painter 1", "Sweep Painter 2"],
            "frames": [],
            "results": {},
        }
    )


def make_metadata(variant_id: str = "default") -> dict[str, Any]:
    return deepcopy(
        {
            "episode_id": "ep_abc123",
            "variant_id": variant_id,
            "started_at": "2026-05-18T10:23:45Z",
            "ended_at": "2026-05-18T10:24:05Z",
            "duration_seconds": 19.4,
            "players": [
                {"slot": 0, "policy_version_id": "polver_1", "policy_name": "champion-v3"},
                {"slot": 1, "policy_version_id": "polver_2", "policy_name": "starter"},
            ],
            "league_id": None,
            "division_id": None,
            "round_id": None,
            "pool_id": None,
            "tags": {},
        }
    )


def make_results(painted: list[int], ticks: int = 100) -> dict[str, Any]:
    return {
        "scores": [float(x) for x in painted],
        "painted_tiles": list(painted),
        "ticks": ticks,
    }


def make_results_happy() -> dict[str, Any]:
    """Slot 0: 47 tiles, slot 1: 38 tiles on a 12x8 grid (96 total, 11 unpainted)."""
    return make_results([47, 38], ticks=100)


def make_results_zero_paint() -> dict[str, Any]:
    return make_results([0, 0], ticks=0)


def make_results_tie() -> dict[str, Any]:
    return make_results([42, 42], ticks=100)


def make_results_missing_field() -> dict[str, Any]:
    """Results JSON missing the required 'ticks' field."""
    return {
        "scores": [47.0, 38.0],
        "painted_tiles": [47, 38],
    }


def make_bundle_bytes(
    *,
    results: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    replay: dict[str, Any] | None = None,
    include_metadata: bool = True,
    ereq_id: str = "ereq_test_001",
    status: str = "success",
) -> bytes:
    """Pack the loose JSON fixtures into a canonical episode bundle zip.

    Layout follows ``artifacts/EPISODE_BUNDLE.md``: a root ``manifest.json``
    mapping tokens to entries inside the zip, plus the JSON files those
    tokens point at.
    """
    results_payload = results if results is not None else make_results_happy()
    metadata_payload = metadata if metadata is not None else make_metadata()
    replay_payload = replay if replay is not None else make_replay()

    include = ["results", "replay"]
    files: dict[str, str] = {"results": "results.json", "replay": "replay.json"}
    if include_metadata:
        include.append("metadata")
        files["metadata"] = "metadata.json"

    manifest = {
        "ereq_id": ereq_id,
        "status": status,
        "include": include,
        "files": files,
    }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("results.json", json.dumps(results_payload))
        zf.writestr("replay.json", json.dumps(replay_payload))
        if include_metadata:
            zf.writestr("metadata.json", json.dumps(metadata_payload))
    return buf.getvalue()


# ---------- helpers ----------


_RENDERABLE_EXTS = {".md", ".html"}
_PINNED_MTIME = (1980, 1, 1, 0, 0, 0)
_EXPECTED_ENTRIES = {"manifest.json", "summary.md", "stats.json"}


def _models(
    *,
    results: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    replay: dict[str, Any] | None = None,
) -> tuple[par.PaintArenaResults, par.EpisodeMetadata, par.PaintArenaReplay]:
    return (
        par.PaintArenaResults.model_validate(results or make_results_happy()),
        par.EpisodeMetadata.model_validate(metadata or make_metadata()),
        par.PaintArenaReplay.model_validate(replay or make_replay()),
    )


def _build_zip(
    *,
    results: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    replay: dict[str, Any] | None = None,
) -> bytes:
    r, m, p = _models(results=results, metadata=metadata, replay=replay)
    return par.build_zip_bytes(results=r, metadata=m, replay=p)


def _extract(payload: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        return {info.filename: zf.read(info.filename) for info in zf.infolist()}


def _manifest_dict(payload: bytes) -> dict[str, Any]:
    return json.loads(_extract(payload)["manifest.json"])


# ---------- pure build_zip_bytes / build_stats ----------


def test_happy_path_zip_entries() -> None:
    payload = _build_zip()
    files = _extract(payload)
    assert set(files.keys()) == _EXPECTED_ENTRIES


def test_manifest_flags_summary_md_as_render() -> None:
    """The in-zip manifest.json flags ``summary.md`` as the render target
    and carries the reporter's id."""
    payload = _build_zip()
    manifest = _manifest_dict(payload)
    assert manifest["render"] == "summary.md"
    assert manifest["reporter_id"] == "paint-arena-summarizer"
    assert manifest["event_log"] is None


def test_manifest_render_target_exists_in_zip_with_renderable_extension() -> None:
    payload = _build_zip()
    files = _extract(payload)
    manifest = _manifest_dict(payload)
    assert manifest["render"] in files
    assert Path(manifest["render"]).suffix.lower() in _RENDERABLE_EXTS


def test_zip_entries_have_pinned_mtime() -> None:
    """All entries pin date_time to (1980,1,1,0,0,0) for byte-identical reruns."""
    payload = _build_zip()
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        for info in zf.infolist():
            assert info.date_time == _PINNED_MTIME, (
                f"{info.filename} has date_time {info.date_time}, expected {_PINNED_MTIME}"
            )


def test_zip_is_well_formed() -> None:
    """Zip bytes are readable (no testzip error) -- platform invalid_output check."""
    with zipfile.ZipFile(io.BytesIO(_build_zip())) as zf:
        assert zf.testzip() is None


def test_happy_path_stats_numbers() -> None:
    results, metadata, replay = _models()
    stats = par.build_stats(results=results, metadata=metadata, config=replay.config)
    assert stats.episode_id == "ep_abc123"
    assert stats.variant_id == "default"
    assert stats.grid.width == 12
    assert stats.grid.height == 8
    assert stats.grid.total_tiles == 96
    assert stats.ticks == 100
    assert stats.unpainted_tiles == 11  # 96 - 47 - 38
    assert stats.winner_slot == 0
    assert stats.margin_tiles == 9
    assert stats.tie is False
    assert [s.slot for s in stats.slots] == [0, 1]
    assert stats.slots[0].policy_name == "champion-v3"
    assert stats.slots[0].painted_tiles == 47
    assert stats.slots[0].share_pct == pytest.approx(48.96, abs=0.01)


def test_happy_path_summary_md_content() -> None:
    payload = _build_zip()
    summary = _extract(payload)["summary.md"].decode("utf-8")
    assert "PaintArena" in summary
    assert "ep_abc123" in summary
    assert "champion-v3" in summary
    assert "Winner" in summary


def test_happy_path_stats_json_content() -> None:
    payload = _build_zip()
    stats = json.loads(_extract(payload)["stats.json"])
    assert stats["episode_id"] == "ep_abc123"
    assert stats["variant_id"] == "default"
    assert stats["grid"] == {"width": 12, "height": 8, "total_tiles": 96}
    assert stats["winner_slot"] == 0
    assert stats["margin_tiles"] == 9
    assert stats["tie"] is False


def test_zero_paint_episode() -> None:
    payload = _build_zip(results=make_results_zero_paint())
    files = _extract(payload)
    stats = json.loads(files["stats.json"])
    assert stats["winner_slot"] is None
    assert stats["tie"] is False
    assert stats["margin_tiles"] == 0
    assert stats["unpainted_tiles"] == 96
    summary = files["summary.md"].decode("utf-8")
    assert "no tiles" in summary.lower()


def test_tie_episode() -> None:
    payload = _build_zip(results=make_results_tie())
    files = _extract(payload)
    stats = json.loads(files["stats.json"])
    assert stats["winner_slot"] is None
    assert stats["tie"] is True
    assert stats["margin_tiles"] == 0
    summary = files["summary.md"].decode("utf-8")
    assert "tied" in summary.lower()


def test_policy_name_falls_back_to_slot_label() -> None:
    metadata_dict = make_metadata()
    metadata_dict["players"][1]["policy_name"] = None
    payload = _build_zip(metadata=metadata_dict)
    stats = json.loads(_extract(payload)["stats.json"])
    assert stats["slots"][1]["policy_name"] == "Slot 1"


def test_replay_missing_config_raises() -> None:
    """Replay payload without a usable `config` block fails fast at validation."""
    bad_replay = make_replay()
    del bad_replay["config"]
    with pytest.raises(ValidationError):
        par.PaintArenaReplay.model_validate(bad_replay)


def test_replay_config_missing_dimensions_raises() -> None:
    """A `config` block missing width/height is a contract violation, not a fallback case."""
    bad_replay = make_replay()
    del bad_replay["config"]["width"]
    with pytest.raises(ValidationError):
        par.PaintArenaReplay.model_validate(bad_replay)


# ---------- end-to-end via file:// bundle URIs ----------


def _setup_bundle(
    tmp_path: Path,
    *,
    results: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    replay: dict[str, Any] | None = None,
    include_metadata: bool = True,
    ereq_id: str = "ereq_test_001",
    status: str = "success",
) -> tuple[dict[str, str], Path]:
    """Write a synthetic bundle zip to ``tmp_path`` and return the env
    var pair plus the output path the reporter should write to."""
    bundle_bytes = make_bundle_bytes(
        results=results,
        metadata=metadata,
        replay=replay,
        include_metadata=include_metadata,
        ereq_id=ereq_id,
        status=status,
    )
    bundle_path = tmp_path / "bundle.zip"
    bundle_path.write_bytes(bundle_bytes)
    out_path = tmp_path / "report.zip"
    env = {
        "COGAME_EPISODE_BUNDLE_URI": bundle_path.as_uri(),
        "COGAME_REPORT_URI": out_path.as_uri(),
    }
    return env, out_path


def _invoke_run(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]) -> None:
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    par.run(par.load_reporter_inputs())


def test_run_happy_path_writes_valid_zip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env, out_path = _setup_bundle(tmp_path)
    _invoke_run(monkeypatch, env)
    payload = out_path.read_bytes()
    files = _extract(payload)
    assert set(files.keys()) == _EXPECTED_ENTRIES
    stats = json.loads(files["stats.json"])
    assert stats["winner_slot"] == 0


def test_run_is_byte_identical_on_rerun(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Determinism: two runs over identical inputs must produce identical bytes."""
    env, out_path = _setup_bundle(tmp_path)
    _invoke_run(monkeypatch, env)
    first = out_path.read_bytes()
    out_path.unlink()
    _invoke_run(monkeypatch, env)
    second = out_path.read_bytes()
    assert first == second


def test_run_falls_back_to_ereq_id_when_metadata_absent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When the bundle has no ``metadata`` token, the reporter uses the
    bundle's ``ereq_id`` as the episode id so the rendered summary still
    names the episode."""
    env, out_path = _setup_bundle(tmp_path, include_metadata=False, ereq_id="ereq_no_meta")
    _invoke_run(monkeypatch, env)
    payload = out_path.read_bytes()
    files = _extract(payload)
    stats = json.loads(files["stats.json"])
    assert stats["episode_id"] == "ereq_no_meta"
    assert stats["variant_id"] == "unknown"


def test_run_failed_bundle_status_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A bundle marked ``status: "failed"`` is not a recoverable input;
    the reporter raises rather than produce a misleading summary."""
    env, out_path = _setup_bundle(tmp_path, status="failed")
    with pytest.raises(RuntimeError, match="failed"):
        _invoke_run(monkeypatch, env)
    assert not out_path.exists()


def test_run_malformed_replay_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Replay without a usable `config` surfaces as a ValidationError, no zip written."""
    bad_replay = make_replay()
    del bad_replay["config"]
    env, out_path = _setup_bundle(tmp_path, replay=bad_replay)
    with pytest.raises(ValidationError):
        _invoke_run(monkeypatch, env)
    assert not out_path.exists()


def test_run_malformed_results_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env, out_path = _setup_bundle(tmp_path, results=make_results_missing_field())
    with pytest.raises(ValidationError):
        _invoke_run(monkeypatch, env)
    assert not out_path.exists()


def test_load_reporter_inputs_missing_env_var_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for k in ("COGAME_EPISODE_BUNDLE_URI", "COGAME_REPORT_URI"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(KeyError):
        par.load_reporter_inputs()
