from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from coworld.episode_bundle import assemble_episode_bundle
from coworld.examples.paintarena.reporter._sdk_vendored.bundle import BundleReader
from coworld.runner.runner import EpisodeArtifacts


def _seed_artifacts(workspace: Path, *, player_slots: int = 2) -> EpisodeArtifacts:
    artifacts = EpisodeArtifacts.create(workspace)
    artifacts.results_path.write_text(json.dumps({"scores": [1.0, 2.0]}), encoding="utf-8")
    artifacts.replay_path.write_bytes(b'{"frames": []}')
    artifacts.game_stdout_path.write_text("out\n", encoding="utf-8")
    artifacts.game_stderr_path.write_text("err\n", encoding="utf-8")
    for slot in range(player_slots):
        artifacts.policy_log_path(slot).write_text(f"player {slot}\n", encoding="utf-8")
    return artifacts


def test_assemble_episode_bundle_maps_tokens_to_entries(tmp_path: Path) -> None:
    artifacts = _seed_artifacts(tmp_path / "cert")

    bundle = assemble_episode_bundle(artifacts, ereq_id="cert-1")

    archive = zipfile.ZipFile(io.BytesIO(bundle))
    manifest = json.loads(archive.read("manifest.json"))

    assert manifest["ereq_id"] == "cert-1"
    assert manifest["status"] == "success"
    assert set(manifest["include"]) == {"results", "replay", "game_logs", "player_logs"}
    assert manifest["files"]["results"] == "results.json"
    assert manifest["files"]["replay"] == "replay.json"
    assert manifest["files"]["game_logs"] == {
        "stdout": "logs/game.stdout.log",
        "stderr": "logs/game.stderr.log",
    }
    assert manifest["files"]["player_logs"] == {
        "0": "logs/policy_agent_0.log",
        "1": "logs/policy_agent_1.log",
    }

    # Every mapped path resolves to a real entry, and replay round-trips.
    names = set(archive.namelist())
    assert {"results.json", "replay.json", "logs/game.stdout.log", "logs/policy_agent_0.log"} <= names
    assert json.loads(archive.read("results.json")) == {"scores": [1.0, 2.0]}
    assert archive.read("replay.json") == b'{"frames": []}'


def test_assemble_episode_bundle_omits_player_logs_when_absent(tmp_path: Path) -> None:
    artifacts = _seed_artifacts(tmp_path / "cert", player_slots=0)

    bundle = assemble_episode_bundle(artifacts, ereq_id="cert-2")

    manifest = json.loads(zipfile.ZipFile(io.BytesIO(bundle)).read("manifest.json"))
    assert "player_logs" not in manifest["include"]
    assert "player_logs" not in manifest["files"]


def test_assemble_episode_bundle_is_readable_by_the_vendored_bundle_reader(tmp_path: Path) -> None:
    # The assembler must produce a manifest the reporter SDK's BundleReader accepts,
    # since that is what real reporters use to consume the bundle.
    artifacts = _seed_artifacts(tmp_path / "cert")
    bundle_path = tmp_path / "bundle.zip"
    bundle_path.write_bytes(assemble_episode_bundle(artifacts, ereq_id="cert-3"))

    with BundleReader(bundle_path.as_uri()) as reader:
        assert reader.inner_manifest().status == "success"
        assert reader.read_json("results") == {"scores": [1.0, 2.0]}
        assert reader.read_bytes("replay") == b'{"frames": []}'
