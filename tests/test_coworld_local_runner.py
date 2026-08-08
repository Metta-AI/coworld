from pathlib import Path

from coworld.runner.runner import EpisodeArtifacts


def test_episode_artifacts_resolve_relative_workspace(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)

    artifacts = EpisodeArtifacts.create(Path("episode"))

    assert artifacts.workspace == tmp_path / "episode"
    assert artifacts.config_path == tmp_path / "episode" / "config.json"
    assert artifacts.policy_artifact_path(0) == tmp_path / "episode" / "policy_artifact_0.zip"
