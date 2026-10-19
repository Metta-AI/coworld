"""Run Paint Arena and its replay through real Docker with creation admission.

Set METTA_COWORLD_REPLAY_SYSTEM_MANIFEST to a rendered Paint Arena manifest
using its legacy container replay viewer and a cached image containing Python.
"""

import os
import subprocess
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import BaseModel

from coworld.runner.local_admission import LocalResourceAdmission
from coworld.runner.local_game_sandbox import GameSandboxReceipt, LocalGameSandbox
from coworld.runner.runner import (
    EpisodeArtifacts,
    LocalIsolationReceipt,
    RunnableLaunchSpec,
    local_episode_network,
    run_coworld_episode,
    verify_replay_loadable,
)
from coworld.types import CoworldEpisodeJobSpec, CoworldManifest


class PaintArenaResults(BaseModel):
    ticks: int
    scores: list[float]


class ImageCommand(BaseModel):
    entrypoint: list[str] | None
    command: list[str] | None


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

    # Replay is a separate native workflow: load the completed game's bytes with
    # a non-host UID so bind-mount access cannot depend on matching host ownership.
    replay_owner = f"coworld-sandbox-{uuid4().hex[:12]}"
    replay_admission = LocalResourceAdmission(tmp_path / "sandbox-admission", replay_owner, "3" * 64)
    replay_admission.initialize()
    sandbox = LocalGameSandbox(uid=os.getuid() + 1, gid=os.getgid() + 1)
    game = replace(RunnableLaunchSpec.from_model(job.game_runnable), sandbox=sandbox)
    try:
        with local_episode_network(
            manifest.game.runnable.image,
            artifacts.logs_dir,
            replay_owner,
            replay_admission,
            creation_seconds=30,
        ) as network:
            verify_replay_loadable(game, artifacts, network=network, timeout_seconds=30, container_prefix=replay_owner)
            assert not (artifacts.workspace / "replay-sandbox.json").exists()
    finally:
        replay_closed = replay_admission.close()
    assert replay_closed.closed and not replay_closed.unresolved
    receipt = GameSandboxReceipt.model_validate_json((artifacts.workspace / "replay-sandbox.json").read_bytes())
    assert receipt.Config.User == f"{sandbox.uid}:{sandbox.gid}"
    assert receipt.HostConfig.ReadonlyRootfs and receipt.HostConfig.CapDrop == ["ALL"]
    for resource in ("container", "network"):
        remaining = subprocess.check_output(
            [
                "docker",
                resource,
                "ls",
                "-aq" if resource == "container" else "-q",
                "--filter",
                f"label=ai.coworld.episode-owner={replay_owner}",
            ],
            text=True,
        )
        assert not remaining.strip(), remaining


def test_file_game_uses_qualified_sandbox(tmp_path: Path) -> None:
    configured = os.environ.get("METTA_COWORLD_FILE_SYSTEM_JOB")
    control_image = os.environ.get("METTA_COWORLD_FILE_CONTROL_IMAGE")
    if not configured or not control_image:
        pytest.skip("Requires a native file-game job, adjacent player-N files, and pinned Python control image")
    source = Path(configured)
    job = CoworldEpisodeJobSpec.model_validate_json(source.read_bytes())
    assert job.manifest.game.player_runtime == "game-hosted"
    owner = f"coworld-file-system-{uuid4().hex[:12]}"
    admission = LocalResourceAdmission(tmp_path / "admission", owner, "2" * 64)
    admission.initialize()
    artifacts = EpisodeArtifacts.create(tmp_path / "episode")
    artifacts.workspace.chmod(0o700)
    artifacts.logs_dir.chmod(0o700)
    sandbox = LocalGameSandbox(uid=os.getuid() + 1, gid=os.getgid() + 1)
    image_command = ImageCommand.model_validate_json(
        subprocess.check_output(
            [
                "docker",
                "image",
                "inspect",
                "--format",
                '{"entrypoint":{{json .Config.Entrypoint}},"command":{{json .Config.Cmd}}}',
                job.game_runnable.image,
            ],
        )
    )
    original_command = job.game_runnable.run or (image_command.entrypoint or []) + (image_command.command or [])
    job.manifest.game.runnable.run = [
        "sh",
        "-ec",
        "test ! -e /coworld/game-sandbox.json; "
        "mkdir /coworld/game-sandbox.json; printf forged > /coworld/game-sandbox.json/payload; "
        "printf forged > /coworld/isolation.json; "
        'printf exercised > /coworld/receipt-tampering; exec "$@"',
        "sandbox-probe",
        *original_command,
    ]
    try:
        run_coworld_episode(
            job,
            artifacts,
            timeout_seconds=300,
            verify_replay=True,
            container_prefix=owner,
            isolated_network_image=control_image,
            resource_admission=admission,
            player_file_paths=[source.parent / f"player-{slot}" for slot in range(len(job.players))],
            game_sandbox=sandbox,
        )
    finally:
        closed = admission.close()
    assert closed.closed and not closed.unresolved
    assert artifacts.results_path.stat().st_size and artifacts.replay_path.stat().st_size
    assert (artifacts.workspace / "receipt-tampering").read_text() == "exercised"
    (retained,) = artifacts.workspace.glob("game-sandbox.json.rejected-*/payload")
    assert retained.read_text() == "forged"
    isolation = LocalIsolationReceipt.model_validate_json((artifacts.workspace / "isolation.json").read_bytes())
    assert isolation.network.Internal
    receipts = ["game-sandbox.json"]
    if job.manifest.game.replay_viewer is None:
        receipts.append("replay-sandbox.json")
    for filename in receipts:
        receipt = GameSandboxReceipt.model_validate_json((artifacts.workspace / filename).read_bytes())
        assert receipt.Config.User == f"{sandbox.uid}:{sandbox.gid}"
        expected_group = sandbox.gid if os.getuid() == 0 else os.getgid()
        assert receipt.HostConfig.GroupAdd == [str(expected_group)] and expected_group != 0
        assert receipt.HostConfig.ReadonlyRootfs and receipt.HostConfig.CapDrop == ["ALL"]
        assert receipt.HostConfig.PidsLimit == sandbox.pids
        assert receipt.HostConfig.Tmpfs == {"/tmp": f"rw,nosuid,nodev,size={sandbox.temporary_bytes}"}
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
