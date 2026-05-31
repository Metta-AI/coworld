from __future__ import annotations

import importlib.util
import json
import zlib
from pathlib import Path

from pytest import MonkeyPatch


def test_paintarena_loads_backend_zlib_replay(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    replay_path = tmp_path / "replay.json.z"
    replay_path.write_bytes(zlib.compress(json.dumps({"frames": []}).encode()))
    monkeypatch.setenv("COGAME_LOAD_REPLAY_URI", replay_path.as_uri())
    server_module = _load_paintarena_server_module()

    assert server_module.load_replay_data(replay_path.as_uri()) == {"frames": []}


def test_paintarena_replay_client_autoplays_and_loops() -> None:
    replay_html = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "coworld"
        / "examples"
        / "paintarena"
        / "game"
        / "client"
        / "replay.html"
    ).read_text(encoding="utf-8")

    assert "if (frames.length === 0) return;" in replay_html
    assert "if (frameIndex >= frames.length - 1) {\n        showFrame(0);\n      } else {" in replay_html
    assert "showFrame(0);\n      start();" in replay_html
    assert "stop();\n      } else" not in replay_html


def _load_paintarena_server_module():
    root = Path(__file__).resolve().parents[1] / "src" / "coworld" / "examples" / "paintarena"
    spec = importlib.util.spec_from_file_location("paintarena_replay_loader_test", root / "game" / "server.py")
    assert spec is not None
    assert spec.loader is not None
    server_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(server_module)
    return server_module
