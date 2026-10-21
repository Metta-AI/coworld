"""Run the complete file-game Docker lifecycle through the public runner.

Build tests/fixtures/failure_declaration and set COWORLD_FAILURE_SYSTEM_IMAGE.
"""

import hashlib
import os
from pathlib import Path
from uuid import uuid4

import pytest

from coworld.runner.io import RunnerEpisodeError
from coworld.runner.runner import EpisodeArtifacts, run_coworld_episode
from coworld.types import CoworldEpisodeJobSpec, CoworldManifest, CoworldPlayerFileSpec


@pytest.mark.parametrize("kind", ["legacy", "player_error", "episode_inconclusive"])
def test_game_interruption_attribution(tmp_path: Path, kind: str) -> None:
    image = os.environ.get("COWORLD_FAILURE_SYSTEM_IMAGE")
    if not image:
        pytest.skip("Requires the real failure-declaration game image and Docker")
    doc = {"type": "text", "value": "Failure attribution system fixture"}
    manifest = CoworldManifest.model_validate(
        {
            "game": {
                "name": "failure-declaration",
                "version": "1.0.0",
                "owner": "system-test",
                "description": "Terminal interruption protocol fixture",
                "player_runtime": "game-hosted",
                "config_schema": {
                    "type": "object",
                    "properties": {
                        "tokens": {"type": "array", "items": {"type": "string"}},
                        "kind": {"type": "string"},
                    },
                    "required": ["tokens", "kind"],
                },
                "results_schema": {"type": "object"},
                "runnable": {"type": "game", "image": image, "resources": {"limits": {"cpu": "1", "memory": "256Mi"}}},
                "protocols": {"player": doc, "global": doc},
                "docs": {"readme": doc},
            },
            "variants": [
                {"id": "standard", "name": "Standard", "description": "Fixture", "game_config": {"kind": "legacy"}}
            ],
            "certification": {"game_config": {"kind": "legacy"}, "players": [{"player_id": "fixture"}]},
            "player": [
                {
                    "type": "player",
                    "id": "fixture",
                    "name": "Fixture",
                    "description": "Fixture file",
                    "file": "player.txt",
                }
            ],
        }
    )
    player = tmp_path / "player.txt"
    player.write_bytes(b"fixture")
    job = CoworldEpisodeJobSpec(
        manifest=manifest,
        game_config={"kind": kind},
        players=[
            CoworldPlayerFileSpec(type="player-file", content_hash=hashlib.sha256(b"fixture").hexdigest(), size_bytes=7)
        ],
    )
    artifacts = EpisodeArtifacts.create(tmp_path / "episode")
    with pytest.raises(RunnerEpisodeError) as raised:
        run_coworld_episode(
            job,
            artifacts,
            player_file_paths=[player],
            timeout_seconds=30,
            container_prefix=f"failure-system-{uuid4().hex[:12]}",
        )
    assert raised.value.error_type == ("episode_inconclusive" if kind == "episode_inconclusive" else "player_error")
    assert raised.value.failed_policy_index == (None if kind == "episode_inconclusive" else 0)
    assert not artifacts.results_path.exists()
    assert artifacts.player_failure_path.is_file()
