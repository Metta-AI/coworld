"""Run Paint Arena and its replay through real Docker with creation admission.

Set METTA_COWORLD_REPLAY_SYSTEM_MANIFEST to a rendered Paint Arena manifest
using its legacy container replay viewer and a cached image containing Python.
"""

import os
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import BaseModel

from coworld.runner.local_admission import LocalResourceAdmission
from coworld.runner.runner import EpisodeArtifacts, LocalIsolationReceipt, run_coworld_episode
from coworld.types import CoworldEpisodeJobSpec, CoworldManifest


class PaintArenaResults(BaseModel):
    ticks: int
    scores: list[float]


def test_episode_and_replay_share_isolation_and_creation_admission(tmp_path: Path) -> None:
    configured = os.environ.get("METTA_COWORLD_REPLAY_SYSTEM_MANIFEST")
    if not configured:
        pytest.skip("Requires a rendered Paint Arena manifest and cached Docker image")
    manifest = CoworldManifest.model_validate_json(Path(configured).read_bytes())
    assert manifest.game.name == "paintarena" and manifest.game.replay_viewer is None
    fixture = manifest.certification
    assert fixture is not None
    players = {player.id: player for player in manifest.player}
    job = CoworldEpisodeJobSpec(
        manifest=manifest,
        game_config=fixture.game_config,
        players=[players[slot.player_id] for slot in fixture.players],
    )
    owner = f"coworld-replay-system-{uuid4().hex[:12]}"
    admission = LocalResourceAdmission(tmp_path / "admission", owner, "1" * 64)
    admission.initialize()
    artifacts = EpisodeArtifacts.create(tmp_path / "episode")
    try:
        run_coworld_episode(
            job,
            artifacts,
            timeout_seconds=90,
            verify_replay=True,
            container_prefix=owner,
            isolated_network_image=manifest.game.runnable.image,
            resource_admission=admission,
        )
    finally:
        closed = admission.close()
    assert closed.closed and not closed.unresolved
    results = PaintArenaResults.model_validate_json(artifacts.results_path.read_bytes())
    assert results.ticks == fixture.game_config["max_ticks"] and len(results.scores) == len(job.players)
    episode = LocalIsolationReceipt.model_validate_json((artifacts.workspace / "isolation.json").read_bytes())
    replay = LocalIsolationReceipt.model_validate_json((artifacts.workspace / "replay-isolation.json").read_bytes())
    assert episode.network.Id == replay.network.Id
    admitted = {path.read_text().strip() for path in admission.root.glob("*.log")}
    assert {
        episode.network.Id,
        *(container.Id for receipt in (episode, replay) for container in receipt.containers),
    } <= admitted
    for resource in ("container", "network"):
        remaining = subprocess.check_output(
            [
                "docker",
                resource,
                "ls",
                "-aq" if resource == "container" else "-q",
                "--filter",
                f"label=ai.coworld.episode-owner={owner}",
            ],
            text=True,
        )
        assert not remaining.strip(), f"Episode left owned {resource} resources"
