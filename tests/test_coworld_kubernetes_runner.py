import gzip
import json
import os
from pathlib import Path
from types import SimpleNamespace

from kubernetes.client.rest import ApiException

from coworld.runner import kubernetes_runner
from coworld.runner import runner as runner_module
from coworld.runner.kubernetes_runner import _collect_logs, _wait_for_results
from coworld.runner.runner import EpisodeArtifacts, PlayerLaunchSpec


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
    def __init__(self, statuses: dict[str, list], missing_pods: set[str] | None = None):
        self._statuses = statuses
        self._missing_pods = missing_pods or set()
        self.log_calls: list[tuple[str, str]] = []

    def read_namespaced_pod(self, *, name: str, namespace: str):
        if name in self._missing_pods:
            raise ApiException(status=404)
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


def test_collect_logs_skips_missing_player_pods(tmp_path):
    artifacts = EpisodeArtifacts.create(tmp_path)
    core_v1 = _FakeLogCoreV1(
        {
            "game-pod": [],
            "player-running": [_container_status("player", running=True)],
        },
        missing_pods={"player-missing"},
    )

    _collect_logs(
        core_v1,
        "default",
        "game-pod",
        ["player-missing", "player-running"],
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


def test_new_workspace_does_not_require_repo_depth(monkeypatch, tmp_path):
    shallow_package_file = tmp_path / "coworld" / "runner" / "runner.py"
    shallow_package_file.parent.mkdir(parents=True)
    shallow_package_file.write_text("", encoding="utf-8")
    monkeypatch.setattr(runner_module, "__file__", str(shallow_package_file))
    monkeypatch.chdir(tmp_path)

    workspace = runner_module._new_workspace("coworld-test-")

    assert workspace.parent == tmp_path / "tmp"


def test_policy_secrets_from_env_loads_and_removes_uri(monkeypatch, tmp_path):
    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_text(
        json.dumps({"policies": {"0": {"ANTHROPIC_API_KEY": "sk-ant-test"}, "2": {"USE_BEDROCK": "true"}}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("POLICY_SECRETS_URI", bundle_path.as_uri())

    assert kubernetes_runner._policy_secrets_from_env() == {
        0: {"ANTHROPIC_API_KEY": "sk-ant-test"},
        2: {"USE_BEDROCK": "true"},
    }
    assert "POLICY_SECRETS_URI" not in os.environ


def test_create_player_pod_injects_policy_secret_env():
    created: dict[str, object] = {}
    core_v1 = SimpleNamespace(
        create_namespaced_pod=lambda *, namespace, body: created.update({"namespace": namespace, "body": body})
    )
    player = PlayerLaunchSpec(
        image="paintbot:latest",
        run=(),
        env={"PUBLIC_SETTING": "visible", "ANTHROPIC_API_KEY": "placeholder"},
    )

    kubernetes_runner._create_player_pod(
        core_v1,
        "jobs",
        "job-player-0",
        0,
        "slot-token",
        player,
        {"ANTHROPIC_API_KEY": "sk-ant-test", "USE_BEDROCK": "true"},
        "job-id",
        "game-service",
        [],
    )

    pod = created["body"]
    env = {env_var.name: env_var.value for env_var in pod.spec.containers[0].env}
    assert env["PUBLIC_SETTING"] == "visible"
    assert env["ANTHROPIC_API_KEY"] == "sk-ant-test"
    assert env["USE_BEDROCK"] == "true"
    assert env["COGAMES_ENGINE_WS_URL"] == "ws://game-service:8080/player?slot=0&token=slot-token"
    assert pod.spec.service_account_name == "episode-runner"


def test_create_player_pod_keeps_default_service_account_without_bedrock():
    created: dict[str, object] = {}
    core_v1 = SimpleNamespace(
        create_namespaced_pod=lambda *, namespace, body: created.update({"namespace": namespace, "body": body})
    )
    player = PlayerLaunchSpec(
        image="paintbot:latest",
        run=(),
        env={},
    )

    kubernetes_runner._create_player_pod(
        core_v1,
        "jobs",
        "job-player-0",
        0,
        "slot-token",
        player,
        {"ANTHROPIC_API_KEY": "sk-ant-test"},
        "job-id",
        "game-service",
        [],
    )

    pod = created["body"]
    assert pod.spec.service_account_name is None
