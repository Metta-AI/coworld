from __future__ import annotations

import json
import zipfile
from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def paint_arena_episode_bundle_path(tmp_path: Path) -> Callable[[list[int], int, int], Path]:
    def build(painted_tiles: list[int], width: int, height: int) -> Path:
        bundle_path = tmp_path / "episode.zip"
        payload = BytesIO()
        with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr("manifest.json", json.dumps({"files": {"results": "results.json", "replay": "replay"}}))
            bundle.writestr(
                "results.json",
                json.dumps(
                    {
                        "scores": [float(value) for value in painted_tiles],
                        "painted_tiles": painted_tiles,
                        "ticks": 100,
                    }
                ),
            )
            bundle.writestr("replay", json.dumps(_replay(width=width, height=height)))
        bundle_path.write_bytes(payload.getvalue())
        return bundle_path

    return build


def _replay(*, width: int, height: int) -> dict[str, Any]:
    return {
        "config": {
            "width": width,
            "height": height,
            "max_ticks": 100,
            "tick_rate": 5,
            "players": [{"name": "A"}, {"name": "B"}],
        },
        "player_names": ["A", "B"],
        "frames": [],
        "results": {},
    }
