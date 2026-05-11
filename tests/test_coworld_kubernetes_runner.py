import gzip
from pathlib import Path
from types import SimpleNamespace

from coworld.runner import kubernetes_runner
from coworld.runner.kubernetes_runner import _wait_for_results
from coworld.runner.runner import EpisodeArtifacts


class _FakeCoreV1:
    def __init__(self, phases: dict[str, str], write_results_on_game_check: Path | None = None):
        self._phases = phases
        self._write_results_on_game_check = write_results_on_game_check

    def read_namespaced_pod(self, *, name: str, namespace: str):
        if name == "game-pod" and self._write_results_on_game_check is not None:
            self._write_results_on_game_check.write_text("{}", encoding="utf-8")
        return SimpleNamespace(
            status=SimpleNamespace(
                phase=self._phases.get(name, "Running"),
                container_statuses=[],
            )
        )


def test_wait_for_results_does_not_wait_for_player_pods_to_succeed(tmp_path):
    artifacts = EpisodeArtifacts.create(tmp_path)
    artifacts.results_path.write_text("{}", encoding="utf-8")
    core_v1 = _FakeCoreV1({"player-0": "Running"})

    _wait_for_results(
        artifacts,
        core_v1,
        "default",
        "game-pod",
        timeout_seconds=0.01,
    )


def test_wait_for_results_ignores_player_pod_failure(tmp_path, monkeypatch):
    artifacts = EpisodeArtifacts.create(tmp_path)
    core_v1 = _FakeCoreV1({"player-0": "Failed"}, write_results_on_game_check=artifacts.results_path)
    monkeypatch.setattr(kubernetes_runner.time, "sleep", lambda _seconds: None)

    _wait_for_results(
        artifacts,
        core_v1,
        "default",
        "game-pod",
        timeout_seconds=1.0,
    )


def test_init_replay_from_env_materializes_compressed_replay(monkeypatch, tmp_path):
    payload = b'{"frames":[{"tick":1}]}'
    monkeypatch.setenv("COGAME_LOAD_REPLAY_URI", "https://storage.example.com/replay.json.z")
    monkeypatch.setattr(kubernetes_runner, "WORKDIR", tmp_path)
    monkeypatch.setattr(kubernetes_runner, "REPLAY_PATH", tmp_path / "replay.json")
    monkeypatch.setattr(kubernetes_runner, "read_data", lambda _uri: gzip.compress(payload))

    kubernetes_runner.init_replay_from_env()

    assert (tmp_path / "replay.json").read_bytes() == payload
