import json
import os
import zipfile
import zlib
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from kubernetes.client.rest import ApiException

from coworld.runner import kubernetes_runner
from coworld.runner import runner as runner_module
from coworld.runner.kubernetes_runner import _collect_logs, _wait_for_episode_artifacts
from coworld.runner.runner import EpisodeArtifacts, EpisodeRunSpec, PlayerLaunchSpec, RunnableLaunchSpec


class _FakeCoreV1:
    def __init__(
        self,
        artifact_writes: list[list[Path]] | None = None,
        game_exit_codes: list[int | None] | None = None,
    ):
        self._artifact_writes = artifact_writes or []
        self._game_exit_codes = game_exit_codes or []
        self.game_read_count = 0

    def read_namespaced_pod(self, *, name: str, namespace: str):
        container_statuses = []
        if name == "game-pod":
            self.game_read_count += 1
            if self.game_read_count <= len(self._artifact_writes):
                for path in self._artifact_writes[self.game_read_count - 1]:
                    path.write_text("{}", encoding="utf-8")
            if self.game_read_count <= len(self._game_exit_codes):
                exit_code = self._game_exit_codes[self.game_read_count - 1]
                if exit_code is not None:
                    container_statuses = [
                        SimpleNamespace(
                            name="game",
                            state=SimpleNamespace(terminated=SimpleNamespace(exit_code=exit_code)),
                        )
                    ]
        return SimpleNamespace(
            status=SimpleNamespace(
                phase="Running",
                container_statuses=container_statuses,
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
    def __init__(
        self,
        statuses: dict[str, list],
        missing_pods: set[str] | None = None,
        log_errors: dict[tuple[str, str], ApiException] | None = None,
    ):
        self._statuses = statuses
        self._missing_pods = missing_pods or set()
        self._log_errors = log_errors or {}
        self.log_calls: list[tuple[str, str]] = []

    def read_namespaced_pod(self, *, name: str, namespace: str):
        if name in self._missing_pods:
            raise ApiException(status=404)
        return SimpleNamespace(status=SimpleNamespace(container_statuses=self._statuses[name]))

    def read_namespaced_pod_log(self, *, name: str, namespace: str, container: str, tail_lines: int):
        self.log_calls.append((name, container))
        if (name, container) in self._log_errors:
            raise self._log_errors[(name, container)]
        return f"{name} {container} logs"


class _FailingCoreV1:
    def read_namespaced_pod(self, *, name: str, namespace: str):
        raise RuntimeError("pod status read failed")


def test_runner_compress_replay_writes_zlib_json_z(tmp_path):
    artifacts = EpisodeArtifacts.create(tmp_path)
    artifacts.replay_path.write_bytes(b'{"events":[]}')

    compressed_path = runner_module.compress_replay(artifacts)

    assert compressed_path.name == "replay.json.z"
    assert zlib.decompress(compressed_path.read_bytes()) == b'{"events":[]}'


def test_kubernetes_compress_replay_writes_zlib_json_z(tmp_path):
    artifacts = EpisodeArtifacts.create(tmp_path)
    artifacts.replay_path.write_bytes(b'{"events":[]}')

    compressed_path = kubernetes_runner._compress_replay(artifacts)

    assert compressed_path.name == "replay.json.z"
    assert zlib.decompress(compressed_path.read_bytes()) == b'{"events":[]}'


def test_require_http_ok_accepts_replay_client_redirect(monkeypatch):
    class RedirectResponse:
        status_code = 307

        def raise_for_status(self):
            raise AssertionError("redirect should be accepted")

    monkeypatch.setattr(runner_module.httpx, "get", lambda _url, timeout: RedirectResponse())

    runner_module._require_http_ok("http://example.test/clients/replay", allow_redirect=True)


def test_run_cogame_episode_omits_empty_policy_names_env(tmp_path, monkeypatch):
    commands: list[list[str]] = []

    class FakeProcess:
        def poll(self):
            return None

    monkeypatch.setattr(runner_module, "_free_local_port", lambda: 12345)
    monkeypatch.setattr(runner_module, "_wait_for_health", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(runner_module, "_require_http_ok", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(runner_module, "_require_global_message", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(runner_module, "_wait_for_game_exit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(runner_module.asyncio, "run", lambda _awaitable: None)

    def fake_popen(command, **_kwargs):
        commands.append(command)
        return FakeProcess()

    monkeypatch.setattr(runner_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(runner_module.subprocess, "run", lambda *_args, **_kwargs: None)

    runner_module.run_cogame_episode(
        EpisodeRunSpec(
            cogame=RunnableLaunchSpec(image="game:latest"),
            players=[],
            tokens=["token-0"],
            policy_names=[],
            artifacts=EpisodeArtifacts.create(tmp_path),
            timeout_seconds=1,
        ),
        verify_replay=False,
    )

    env_values = [value for index, value in enumerate(commands[0]) if index > 0 and commands[0][index - 1] == "-e"]
    assert all(not value.startswith("COGAMES_POLICY_NAMES=") for value in env_values)


def test_wait_for_episode_artifacts_skips_pod_status_after_results_when_replay_not_required(tmp_path):
    artifacts = EpisodeArtifacts.create(tmp_path)
    artifacts.results_path.write_text("{}", encoding="utf-8")

    _wait_for_episode_artifacts(
        artifacts,
        _FailingCoreV1(),
        "default",
        "game-pod",
        timeout_seconds=0.01,
        require_replay=False,
    )


def test_wait_for_episode_artifacts_returns_after_results_written_when_replay_not_required(tmp_path, monkeypatch):
    artifacts = EpisodeArtifacts.create(tmp_path)
    core_v1 = _FakeCoreV1(artifact_writes=[[artifacts.results_path]])
    monkeypatch.setattr(kubernetes_runner.time, "sleep", lambda _seconds: None)

    _wait_for_episode_artifacts(
        artifacts,
        core_v1,
        "default",
        "game-pod",
        timeout_seconds=1.0,
        require_replay=False,
    )


def test_wait_for_episode_artifacts_waits_for_replay_after_results(tmp_path, monkeypatch):
    artifacts = EpisodeArtifacts.create(tmp_path)
    core_v1 = _FakeCoreV1(
        artifact_writes=[[artifacts.results_path], [artifacts.replay_path]],
        game_exit_codes=[None, 0],
    )
    monkeypatch.setattr(kubernetes_runner.time, "sleep", lambda _seconds: None)

    _wait_for_episode_artifacts(
        artifacts,
        core_v1,
        "default",
        "game-pod",
        timeout_seconds=1.0,
        require_replay=True,
    )

    assert artifacts.replay_path.exists()
    assert core_v1.game_read_count == 2


def test_wait_for_episode_artifacts_fails_when_game_exits_without_replay(tmp_path):
    artifacts = EpisodeArtifacts.create(tmp_path)
    core_v1 = _FakeCoreV1(
        artifact_writes=[[artifacts.results_path]],
        game_exit_codes=[0],
    )

    with pytest.raises(TimeoutError, match="replay.json"):
        _wait_for_episode_artifacts(
            artifacts,
            core_v1,
            "default",
            "game-pod",
            timeout_seconds=1.0,
            require_replay=True,
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


def test_collect_logs_records_player_log_errors_without_failing(tmp_path):
    artifacts = EpisodeArtifacts.create(tmp_path)
    core_v1 = _FakeLogCoreV1(
        {
            "game-pod": [],
            "player-broken": [_container_status("player", running=True)],
            "player-running": [_container_status("player", running=True)],
        },
        log_errors={("player-broken", "player"): ApiException(status=500, reason="kubelet timeout")},
    )

    _collect_logs(
        core_v1,
        "default",
        "game-pod",
        ["player-broken", "player-running"],
        artifacts,
    )

    assert artifacts.game_stdout_path.read_text(encoding="utf-8") == "game-pod game logs"
    assert "Failed to collect Kubernetes logs for pod player-broken container player" in artifacts.policy_log_path(
        0
    ).read_text(encoding="utf-8")
    assert artifacts.policy_log_path(1).read_text(encoding="utf-8") == "player-running player logs"
    assert core_v1.log_calls == [("game-pod", "game"), ("player-broken", "player"), ("player-running", "player")]


def test_collect_logs_records_game_log_read_failures(tmp_path):
    artifacts = EpisodeArtifacts.create(tmp_path)
    core_v1 = _FakeLogCoreV1(
        {
            "game-pod": [],
            "player-running": [_container_status("player", running=True)],
        },
        log_errors={("game-pod", "game"): ApiException(status=500, reason="kubelet timeout")},
    )

    _collect_logs(
        core_v1,
        "default",
        "game-pod",
        ["player-running"],
        artifacts,
    )

    assert artifacts.game_stdout_path.read_text(encoding="utf-8").startswith(
        "Failed to collect Kubernetes logs for pod game-pod container game:"
    )
    assert artifacts.policy_log_path(0).read_text(encoding="utf-8") == "player-running player logs"
    assert core_v1.log_calls == [("game-pod", "game"), ("player-running", "player")]


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
    assert pod.metadata.annotations == {"karpenter.sh/do-not-disrupt": "true"}
    assert pod.spec.service_account_name == "episode-runner"


def test_kubernetes_runner_uses_direct_player_urls_without_address():
    player = PlayerLaunchSpec(image="paintbot:latest", run=(), env={})

    assert kubernetes_runner._player_client_url(1, "slot-token", player) == (
        "http://127.0.0.1:8080/clients/player?slot=1&token=slot-token"
    )
    assert kubernetes_runner._player_service_ws_url("game-service", 1, "slot-token", player) == (
        "ws://game-service:8080/player?slot=1&token=slot-token"
    )


def test_run_from_env_writes_error_info_on_failure(monkeypatch, tmp_path):
    events: list[str] = []

    monkeypatch.setenv("COWORLD_WORKDIR", str(tmp_path))
    monkeypatch.setattr(kubernetes_runner, "_read_job_spec", lambda: object())
    monkeypatch.setattr(kubernetes_runner.EpisodeArtifacts, "create", lambda workdir, prefix: object())
    monkeypatch.setattr(
        kubernetes_runner,
        "_write_error_info",
        lambda exc: events.append(str(exc)),
    )

    def run_episode(*args, **kwargs):
        raise RuntimeError("episode failed")

    monkeypatch.setattr(kubernetes_runner, "_run_kubernetes_episode", run_episode)

    with pytest.raises(RuntimeError, match="episode failed"):
        kubernetes_runner.run_from_env()

    assert events == ["episode failed"]


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


def test_run_from_env_uploads_debug_logs_on_failure(monkeypatch, tmp_path):
    """When the episode crashes, collected game/player logs must be uploaded
    before the pod is deleted — otherwise they're lost forever."""
    workspace = tmp_path / "workspace"
    artifacts = EpisodeArtifacts.create(workspace)

    # Simulate logs that _collect_logs would have written
    artifacts.game_stdout_path.write_text("game crashed with segfault", encoding="utf-8")
    artifacts.policy_log_path(0).write_text("player 0 timeout waiting for server", encoding="utf-8")
    artifacts.policy_log_path(1).write_text("player 1 connection refused", encoding="utf-8")

    # Set up file:// destinations for uploads
    debug_dest = tmp_path / "uploaded" / "debug.zip"
    policy0_dest = tmp_path / "uploaded" / "policy_0.txt"
    policy1_dest = tmp_path / "uploaded" / "policy_1.txt"
    error_dest = tmp_path / "uploaded" / "error_info.json"

    monkeypatch.setenv("COWORLD_WORKDIR", str(workspace))
    monkeypatch.setenv("DEBUG_URI", debug_dest.as_uri())
    monkeypatch.setenv("ERROR_INFO_URI", error_dest.as_uri())
    monkeypatch.setenv(
        "POLICY_LOG_URLS",
        json.dumps({"0": policy0_dest.as_uri(), "1": policy1_dest.as_uri()}),
    )

    monkeypatch.setattr(kubernetes_runner, "_read_job_spec", lambda: object())
    monkeypatch.setattr(kubernetes_runner.EpisodeArtifacts, "create", lambda workdir, prefix: artifacts)

    def run_episode(*args, **kwargs):
        raise TimeoutError("Timed out waiting for game container")

    monkeypatch.setattr(kubernetes_runner, "_run_kubernetes_episode", run_episode)

    with pytest.raises(TimeoutError):
        kubernetes_runner.run_from_env()

    assert debug_dest.exists()
    with zipfile.ZipFile(BytesIO(debug_dest.read_bytes())) as zf:
        names = set(zf.namelist())
        assert "game.stdout.log" in names
        assert "policy_agent_0.txt" in names
        assert "policy_agent_1.txt" in names
        assert zf.read("game.stdout.log").decode() == "game crashed with segfault"
        assert zf.read("policy_agent_0.txt").decode() == "player 0 timeout waiting for server"

    # Verify per-policy logs were uploaded individually
    assert policy0_dest.read_text(encoding="utf-8") == "player 0 timeout waiting for server"
    assert policy1_dest.read_text(encoding="utf-8") == "player 1 connection refused"
