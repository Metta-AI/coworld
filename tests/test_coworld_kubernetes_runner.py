import gzip
from pathlib import Path
from types import SimpleNamespace

from coworld.runner import kubernetes_runner
from coworld.runner.kubernetes_runner import _collect_logs, _wait_for_results
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


def _container_status(name: str, *, running: bool = False, terminated: bool = False, waiting: bool = False):
    return SimpleNamespace(
        name=name,
        state=SimpleNamespace(
            running=object() if running else None,
            terminated=object() if terminated else None,
            waiting=object() if waiting else None,
        ),
    )


class _FakeLogCoreV1:
    def __init__(self, statuses: dict[str, list]):
        self._statuses = statuses
        self.log_calls: list[tuple[str, str]] = []

    def read_namespaced_pod(self, *, name: str, namespace: str):
        return SimpleNamespace(status=SimpleNamespace(container_statuses=self._statuses[name]))

    def read_namespaced_pod_log(self, *, name: str, namespace: str, container: str, tail_lines: int):
        self.log_calls.append((name, container))
        return f"{name} {container} logs"


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


def test_collect_logs_skips_player_pods_that_have_not_started(tmp_path):
    artifacts = EpisodeArtifacts.create(tmp_path)
    core_v1 = _FakeLogCoreV1(
        {
            "player-waiting": [_container_status("player", waiting=True)],
            "player-running": [_container_status("player", running=True)],
        }
    )

    _collect_logs(
        core_v1,
        "default",
        "game-pod",
        ["player-waiting", "player-running"],
        artifacts,
    )

    assert artifacts.game_stdout_path.read_text(encoding="utf-8") == "game-pod game logs"
    assert not artifacts.policy_log_path(0).exists()
    assert artifacts.policy_log_path(1).read_text(encoding="utf-8") == "player-running player logs"
    assert core_v1.log_calls == [("game-pod", "game"), ("player-running", "player")]


def test_init_replay_from_env_materializes_compressed_replay(monkeypatch, tmp_path):
    payload = b'{"frames":[{"tick":1}]}'
    monkeypatch.setenv("COGAME_LOAD_REPLAY_URI", "https://storage.example.com/replay.json.z")
    monkeypatch.setattr(kubernetes_runner, "WORKDIR", tmp_path)
    monkeypatch.setattr(kubernetes_runner, "REPLAY_PATH", tmp_path / "replay.json")
    monkeypatch.setattr(kubernetes_runner, "read_data", lambda _uri: gzip.compress(payload))

    kubernetes_runner.init_replay_from_env()

    assert (tmp_path / "replay.json").read_bytes() == payload
