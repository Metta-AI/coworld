import json
from pathlib import Path
from types import SimpleNamespace

from pytest import MonkeyPatch
from pytest_httpserver import HTTPServer
from typer.testing import CliRunner

from coworld.cli import app

COWORLD_ID = "cow_00000000-0000-0000-0000-000000000001"
COWORLD_PATH = f"/v2/coworlds/{COWORLD_ID}"


def test_coworld_play_accepts_backend_coworld_path(httpserver: HTTPServer, monkeypatch: MonkeyPatch) -> None:
    manifest = {"game": {"name": "downloaded"}}
    httpserver.expect_request(COWORLD_PATH).respond_with_json({"manifest": manifest})
    captured: dict[str, object] = {}

    def fake_play_coworld(manifest_path: Path, **kwargs: object) -> SimpleNamespace:
        captured["manifest"] = json.loads(manifest_path.read_text())
        artifacts = SimpleNamespace(
            workspace=Path("/tmp/workspace"),
            results_path=Path("/tmp/results.json"),
            replay_path=Path("/tmp/replay.json"),
            logs_dir=Path("/tmp/logs"),
        )
        return SimpleNamespace(session=SimpleNamespace(artifacts=artifacts), results={})

    monkeypatch.setattr("coworld.cli.play_coworld", fake_play_coworld)

    result = CliRunner().invoke(app, ["play", COWORLD_PATH, "--server", httpserver.url_for("")])

    assert result.exit_code == 0, result.output
    assert captured["manifest"] == manifest
