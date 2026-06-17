import json
import os
import socket
import subprocess
import zipfile
import zlib
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from kubernetes import client
from kubernetes.client.rest import ApiException

from coworld.runner import io as runner_io
from coworld.runner import kubernetes_runner
from coworld.runner import runner as runner_module
from coworld.runner.kubernetes_runner import _collect_logs, _upload_outputs, _wait_for_episode_artifacts
from coworld.runner.phase_timings import EpisodePhaseTimings
from coworld.runner.runner import EpisodeArtifacts, EpisodeRunSpec, PlayerLaunchSpec, RunnableLaunchSpec


def test_load_incluster_config_sets_bearer_token_key(monkeypatch):
    kube_config = client.Configuration()
    kube_config.api_key["authorization"] = "bearer test-token"
    kube_config.api_key_prefix = {}
    captured_configs = []

    monkeypatch.setattr(kubernetes_runner.config, "load_incluster_config", lambda: None)
    monkeypatch.setattr(kubernetes_runner.client.Configuration, "get_default_copy", lambda: kube_config)
    monkeypatch.setattr(kubernetes_runner.client.Configuration, "set_default", captured_configs.append)

    kubernetes_runner._load_incluster_config()

    assert kube_config.api_key["authorization"] == "bearer test-token"
    assert kube_config.api_key["BearerToken"] == "test-token"
    assert kube_config.api_key_prefix["BearerToken"] == "Bearer"
    assert captured_configs == [kube_config]


class _FakeCoreV1:
    def __init__(
        self,
        artifact_writes: list[list[Path]] | None = None,
        game_exit_codes: list[int | None] | None = None,
        player_statuses: dict[str, list] | None = None,
    ):
        self._artifact_writes = artifact_writes or []
        self._game_exit_codes = game_exit_codes or []
        self._player_statuses = player_statuses or {}
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
        elif name in self._player_statuses:
            container_statuses = self._player_statuses[name]
        return SimpleNamespace(
            status=SimpleNamespace(
                phase="Running",
                container_statuses=container_statuses,
            )
        )


def _container_status(
    name: str,
    *,
    running: bool = False,
    waiting: bool = False,
    exit_code: int | None = None,
    reason: str | None = None,
    message: str | None = None,
):
    return SimpleNamespace(
        name=name,
        state=SimpleNamespace(
            running=object() if running else None,
            terminated=SimpleNamespace(exit_code=exit_code, reason=reason, message=message)
            if exit_code is not None
            else None,
            waiting=SimpleNamespace(reason=reason, message=message) if waiting else None,
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
        return f"{name} {container} combined stdout stderr logs"


class _FailingCoreV1:
    def read_namespaced_pod(self, *, name: str, namespace: str):
        raise RuntimeError("pod status read failed")


def test_upload_outputs_zlib_compresses_replay_at_boundary(tmp_path, monkeypatch):
    artifacts = EpisodeArtifacts.create(tmp_path)
    artifacts.results_path.write_text("{}", encoding="utf-8")
    replay_payload = b"\x00crewrift-replay-bytes\xff"
    artifacts.replay_path.write_bytes(replay_payload)
    uploads: list[tuple[str, bytes, str]] = []

    monkeypatch.setattr(
        kubernetes_runner,
        "upload_data",
        lambda uri, data, *, content_type: uploads.append((uri, data, content_type)),
    )
    monkeypatch.setenv("RESULTS_URI", "file:///tmp/results-out.json")
    monkeypatch.setenv("REPLAY_URI", "file:///tmp/replay-out.bin")
    monkeypatch.delenv("DEBUG_URI", raising=False)
    monkeypatch.delenv("POLICY_LOG_URLS", raising=False)

    _upload_outputs(artifacts)

    replay_uploads = [upload for upload in uploads if upload[0] == "file:///tmp/replay-out.bin"]
    assert len(replay_uploads) == 1
    _, replay_bytes, content_type = replay_uploads[0]
    assert content_type == "application/x-compress"
    assert zlib.decompress(replay_bytes) == replay_payload
    assert not (artifacts.workspace / "replay.z").exists()


def test_upload_timings_writes_model_json_to_env_uri(monkeypatch):
    uploads: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        kubernetes_runner,
        "upload_data",
        lambda uri, data, *, content_type: uploads.append((uri, data, content_type)),
    )
    monkeypatch.setenv("WORKER_TIMINGS_URI", "file:///tmp/timings.json")
    timings = EpisodePhaseTimings(
        game_boot_s=1.0, player_launch_s=2.0, first_step_s=3.0, gameplay_s=4.0, artifact_upload_s=0.5
    )

    kubernetes_runner._upload_timings(timings)

    assert len(uploads) == 1
    uri, data, content_type = uploads[0]
    assert uri == "file:///tmp/timings.json"
    assert content_type == "application/json"
    assert EpisodePhaseTimings.model_validate_json(data).first_step_s == 3.0


def test_upload_timings_noop_without_env(monkeypatch):
    uploads: list[object] = []
    monkeypatch.setattr(kubernetes_runner, "upload_data", lambda *a, **k: uploads.append(a))
    monkeypatch.delenv("WORKER_TIMINGS_URI", raising=False)

    kubernetes_runner._upload_timings(
        EpisodePhaseTimings(game_boot_s=1, player_launch_s=1, first_step_s=1, gameplay_s=1, artifact_upload_s=1)
    )

    assert uploads == []


def test_require_http_ok_accepts_replay_client_redirect(monkeypatch):
    class RedirectResponse:
        status_code = 307

        def raise_for_status(self):
            raise AssertionError("redirect should be accepted")

    monkeypatch.setattr(runner_module.httpx, "get", lambda _url, timeout: RedirectResponse())

    runner_module._require_http_ok("http://example.test/client/replay", allow_redirect=True)


def test_run_episode_containers_uses_docker_dns_and_omits_policy_names_env(tmp_path, monkeypatch):
    commands: list[list[str]] = []
    run_commands: list[list[str]] = []

    class FakeProcess:
        def poll(self):
            return None

    async def noop_async(*_args, **_kwargs):
        return None

    monkeypatch.setattr(runner_module, "_free_local_port", lambda: 12345)
    monkeypatch.setattr(runner_module.secrets, "token_hex", lambda _bytes: "session-1")
    monkeypatch.setattr(runner_module, "_wait_for_health", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(runner_module, "_require_http_ok", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(runner_module, "_require_bad_player_rejected", noop_async)
    monkeypatch.setattr(runner_module, "_require_global_message", noop_async)
    monkeypatch.setattr(runner_module, "_wait_for_game_exit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(runner_module, "_wait_for_player_exit", lambda *_args, **_kwargs: None)

    def fake_popen(command, **_kwargs):
        commands.append(command)
        return FakeProcess()

    def fake_run(command, **_kwargs):
        run_commands.append(command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(runner_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(runner_module.subprocess, "run", fake_run)

    runner_module.run_episode_containers(
        EpisodeRunSpec(
            game=RunnableLaunchSpec(image="game:latest"),
            players=[PlayerLaunchSpec(image="player:latest", env={"PLAYER_MODE": "test"})],
            tokens=["token-0"],
            artifacts=EpisodeArtifacts.create(tmp_path),
            timeout_seconds=1,
            container_prefix="coworld-run",
        ),
        verify_replay=False,
    )

    game_command, player_command = commands
    env_values = [value for index, value in enumerate(game_command) if index > 0 and game_command[index - 1] == "-e"]
    assert all(not value.startswith("COWORLD_POLICY_NAMES=") for value in env_values)
    assert run_commands[0] == ["docker", "network", "inspect", runner_module.LOCAL_DOCKER_NETWORK]
    assert "coworld-run-game-session-1" in game_command
    assert "coworld-run-player-session-1-0" in player_command
    assert "--network" in game_command
    assert game_command[game_command.index("--network") + 1] == runner_module.LOCAL_DOCKER_NETWORK
    assert "--network-alias" in game_command
    assert game_command[game_command.index("--network-alias") + 1] == "coworld-game-session-1"
    assert "--network" in player_command
    assert player_command[player_command.index("--network") + 1] == runner_module.LOCAL_DOCKER_NETWORK
    assert "--add-host" not in player_command
    assert "host.docker.internal:host-gateway" not in player_command
    assert "COWORLD_PLAYER_WS_URL=ws://coworld-game-session-1:8080/player?slot=0&token=token-0" in player_command
    # The player container is given a workspace mount and a file:// artifact upload URL for local parity.
    workspace = str(EpisodeArtifacts.create(tmp_path).workspace)
    assert f"{workspace}:/coworld-artifact:rw" in player_command
    assert "COWORLD_PLAYER_ARTIFACT_UPLOAD_URL=file:///coworld-artifact/policy_artifact_0.zip" in player_command


def test_run_episode_containers_player_artifact_round_trips_to_workspace(tmp_path, monkeypatch):
    """A player that uploads to COWORLD_PLAYER_ARTIFACT_UPLOAD_URL lands a file the runner can find.

    Simulates the player by having the fake player process write to the file:// URL the runner
    injected (the local mount maps /coworld-artifact -> workspace), then asserts the bytes appear
    at the runner's policy_artifact_path(slot). This exercises the real io.write_data file:// path
    and confirms the runner and player agree on the artifact location.
    """
    artifacts = EpisodeArtifacts.create(tmp_path)

    class FakeProcess:
        def poll(self):
            return None

    async def noop_async(*_args, **_kwargs):
        return None

    monkeypatch.setattr(runner_module, "_free_local_port", lambda: 12345)
    monkeypatch.setattr(runner_module.secrets, "token_hex", lambda _bytes: "session-1")
    monkeypatch.setattr(runner_module, "_wait_for_health", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(runner_module, "_require_http_ok", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(runner_module, "_require_bad_player_rejected", noop_async)
    monkeypatch.setattr(runner_module, "_require_global_message", noop_async)
    monkeypatch.setattr(runner_module, "_wait_for_game_exit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(runner_module, "_wait_for_player_exit", lambda *_args, **_kwargs: None)

    def fake_popen(command, **_kwargs):
        # Act as the player: write to the artifact URL the runner injected. The local mount maps
        # /coworld-artifact onto the workspace, so rewrite that container path to the host workspace.
        for index, token in enumerate(command):
            if token == "-e" and command[index + 1].startswith("COWORLD_PLAYER_ARTIFACT_UPLOAD_URL="):
                url = command[index + 1].split("=", 1)[1]
                host_url = url.replace("file:///coworld-artifact/", f"file://{artifacts.workspace}/")
                runner_io.write_data(host_url, b"player-artifact-zip-bytes", content_type="application/zip")
        return FakeProcess()

    monkeypatch.setattr(runner_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        runner_module.subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(command, 0),
    )

    runner_module.run_episode_containers(
        EpisodeRunSpec(
            game=RunnableLaunchSpec(image="game:latest"),
            players=[PlayerLaunchSpec(image="player:latest")],
            tokens=["token-0"],
            artifacts=artifacts,
            timeout_seconds=1,
            container_prefix="coworld-run",
        ),
        verify_replay=False,
    )

    artifact_path = artifacts.policy_artifact_path(0)
    assert artifact_path.exists()
    assert artifact_path.read_bytes() == b"player-artifact-zip-bytes"


def test_run_episode_containers_verifies_hosted_zlib_replay_uri(tmp_path, monkeypatch):
    commands: list[list[str]] = []
    mounted_replay_bytes: list[bytes] = []
    artifacts = EpisodeArtifacts.create(tmp_path)
    replay_payload = b"\x00crewrift-replay-bytes\xff"
    artifacts.replay_path.write_bytes(replay_payload)

    class FakeProcess:
        def poll(self):
            return None

    async def noop_async(*_args, **_kwargs):
        return None

    monkeypatch.setattr(runner_module, "_free_local_port", lambda: 12345)
    monkeypatch.setattr(runner_module.secrets, "token_hex", lambda _bytes: "session-1")
    monkeypatch.setattr(runner_module, "_wait_for_health", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(runner_module, "_require_http_ok", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(runner_module, "_require_bad_player_rejected", noop_async)
    monkeypatch.setattr(runner_module, "_require_global_message", noop_async)
    monkeypatch.setattr(runner_module, "_require_replay_message", noop_async)
    monkeypatch.setattr(runner_module, "_wait_for_game_exit", lambda *_args, **_kwargs: None)

    def fake_popen(command, **_kwargs):
        commands.append(command)
        if "coworld-run-replay-session-1" in command:
            replay_mount = next(arg for index, arg in enumerate(command) if index > 0 and command[index - 1] == "-v")
            mounted_replay_dir = Path(replay_mount.removesuffix(":/coworld-replay:ro"))
            mounted_replay_bytes.append((mounted_replay_dir / "replay.z").read_bytes())
        return FakeProcess()

    monkeypatch.setattr(runner_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        runner_module.subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(command, 0),
    )

    runner_module.run_episode_containers(
        EpisodeRunSpec(
            game=RunnableLaunchSpec(image="game:latest"),
            players=[],
            tokens=[],
            artifacts=artifacts,
            timeout_seconds=1,
            container_prefix="coworld-run",
        ),
        verify_replay=True,
    )

    _game_command, replay_command = commands
    assert f"{runner_module.REPLAY_LOAD_ENV_VAR}=file:///coworld-replay/replay.z" in replay_command
    assert zlib.decompress(mounted_replay_bytes[0]) == replay_payload


def test_ensure_local_docker_network_reuses_existing_network(monkeypatch):
    calls: list[list[str]] = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(runner_module.subprocess, "run", fake_run)

    runner_module.ensure_local_docker_network()

    assert calls == [["docker", "network", "inspect", runner_module.LOCAL_DOCKER_NETWORK]]


def test_ensure_local_docker_network_creates_missing_network(monkeypatch):
    calls: list[list[str]] = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 1 if command[1:3] == ["network", "inspect"] else 0)

    monkeypatch.setattr(runner_module.subprocess, "run", fake_run)

    runner_module.ensure_local_docker_network()

    assert calls == [
        ["docker", "network", "inspect", runner_module.LOCAL_DOCKER_NETWORK],
        ["docker", "network", "create", runner_module.LOCAL_DOCKER_NETWORK],
    ]


def test_ensure_local_docker_network_accepts_concurrent_create(monkeypatch):
    calls: list[list[str]] = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        if command[1:3] == ["network", "inspect"]:
            return subprocess.CompletedProcess(command, 0 if len(calls) == 3 else 1)
        return subprocess.CompletedProcess(command, 1, stderr="network with name coworld-local already exists")

    monkeypatch.setattr(runner_module.subprocess, "run", fake_run)

    runner_module.ensure_local_docker_network()

    assert calls == [
        ["docker", "network", "inspect", runner_module.LOCAL_DOCKER_NETWORK],
        ["docker", "network", "create", runner_module.LOCAL_DOCKER_NETWORK],
        ["docker", "network", "inspect", runner_module.LOCAL_DOCKER_NETWORK],
    ]


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
        player_statuses={
            "player-0": [_container_status("player", exit_code=0, reason="Completed")],
        },
    )

    with pytest.raises(TimeoutError, match="replay"):
        _wait_for_episode_artifacts(
            artifacts,
            core_v1,
            "default",
            "game-pod",
            ["player-0"],
            timeout_seconds=1.0,
            require_replay=True,
        )


@pytest.mark.parametrize(
    ("player_status", "expected_message"),
    [
        (_container_status("player", exit_code=1, reason="Error", message="websocket returned 403"), "websocket"),
        (
            _container_status("player", waiting=True, reason="ImagePullBackOff", message="pull failed"),
            "ImagePullBackOff",
        ),
    ],
)
def test_wait_for_episode_artifacts_reports_failed_player_on_timeout(tmp_path, player_status, expected_message):
    artifacts = EpisodeArtifacts.create(tmp_path)
    core_v1 = _FakeCoreV1(player_statuses={"player-0": [player_status]})

    with pytest.raises(kubernetes_runner.PlayerPodFailure) as exc_info:
        _wait_for_episode_artifacts(
            artifacts,
            core_v1,
            "default",
            "game-pod",
            ["player-0"],
            timeout_seconds=0.01,
            require_replay=False,
        )

    assert exc_info.value.failed_policy_index == 0
    assert expected_message in str(exc_info.value)


def test_wait_for_episode_artifacts_ignores_clean_player_exit_on_timeout(tmp_path):
    artifacts = EpisodeArtifacts.create(tmp_path)
    core_v1 = _FakeCoreV1(
        player_statuses={
            "player-0": [_container_status("player", exit_code=0, reason="Completed")],
        }
    )

    with pytest.raises(TimeoutError, match="results"):
        _wait_for_episode_artifacts(
            artifacts,
            core_v1,
            "default",
            "game-pod",
            ["player-0"],
            timeout_seconds=0.01,
            require_replay=False,
        )


def test_wait_for_episode_artifacts_ignores_player_pods(tmp_path, monkeypatch):
    # Regression: episode success depends only on the game container. A player pod
    # exiting (even cleanly) or disappearing must not fail the episode. Previously a
    # player pod that exited 0 before results were written was reported as a
    # policy_error and failed the entire round.
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
        ["player-0"],
        timeout_seconds=1.0,
        require_replay=True,
    )

    assert artifacts.replay_path.exists()


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

    assert artifacts.game_stdout_path.read_text(encoding="utf-8") == "game-pod game combined stdout stderr logs"
    assert not artifacts.policy_log_path(0).exists()
    assert artifacts.policy_log_path(1).read_text(encoding="utf-8") == (
        "player-running player combined stdout stderr logs"
    )
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

    assert artifacts.game_stdout_path.read_text(encoding="utf-8") == "game-pod game combined stdout stderr logs"
    assert not artifacts.policy_log_path(0).exists()
    assert artifacts.policy_log_path(1).read_text(encoding="utf-8") == (
        "player-running player combined stdout stderr logs"
    )
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

    assert artifacts.game_stdout_path.read_text(encoding="utf-8") == "game-pod game combined stdout stderr logs"
    assert "Failed to collect Kubernetes logs for pod player-broken container player" in artifacts.policy_log_path(
        0
    ).read_text(encoding="utf-8")
    assert artifacts.policy_log_path(1).read_text(encoding="utf-8") == (
        "player-running player combined stdout stderr logs"
    )
    assert core_v1.log_calls == [
        ("game-pod", "game"),
        ("player-broken", "player"),
        ("player-running", "player"),
    ]


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
    assert artifacts.policy_log_path(0).read_text(encoding="utf-8") == (
        "player-running player combined stdout stderr logs"
    )
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


def test_run_kubernetes_episode_defaults_player_resource_requests(monkeypatch, tmp_path):
    artifacts = EpisodeArtifacts.create(tmp_path)
    artifacts.results_path.write_text("{}", encoding="utf-8")
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"tokens": ["slot-token"]}), encoding="utf-8")
    created: list[tuple[str, str]] = []

    async def noop_async(*_args, **_kwargs):
        return None

    monkeypatch.setattr(kubernetes_runner, "STATE_PATH", state_path)
    monkeypatch.setattr(kubernetes_runner, "_load_incluster_config", lambda: None)
    monkeypatch.setattr(kubernetes_runner.client, "CoreV1Api", lambda: object())
    monkeypatch.setattr(kubernetes_runner, "_create_game_service", lambda *_args: None)
    monkeypatch.setattr(kubernetes_runner, "_wait_for_health", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(kubernetes_runner, "_require_http_ok", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(kubernetes_runner, "_require_bad_player_rejected", noop_async)
    monkeypatch.setattr(kubernetes_runner, "_require_global_message", noop_async)
    monkeypatch.setattr(kubernetes_runner, "_wait_for_episode_artifacts", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(kubernetes_runner, "validate_json_schema", lambda *_args: None)
    monkeypatch.setattr(kubernetes_runner, "_collect_logs", lambda *_args: None)
    monkeypatch.setattr(kubernetes_runner, "_delete_child_resources", lambda *_args: None)
    monkeypatch.setattr(kubernetes_runner, "_policy_secrets_from_env", lambda: {})
    monkeypatch.delenv("COWORLD_PLAYER_CPU_REQUEST", raising=False)
    monkeypatch.delenv("COWORLD_PLAYER_MEMORY_REQUEST", raising=False)
    monkeypatch.setenv("JOB_NAMESPACE", "jobs")
    monkeypatch.setenv("COWORLD_SERVICE_NAME", "game-service")
    monkeypatch.setenv("JOB_ID", "job-id")
    monkeypatch.setenv("POD_NAME", "game-pod")
    monkeypatch.setenv("POD_UID", "pod-uid")

    def create_player_pod(
        _core_v1,
        _namespace,
        _name,
        _slot,
        _token,
        _player,
        _policy_secret_env,
        _job_id,
        _service_name,
        player_cpu_request,
        player_memory_request,
        _owner_references,
    ):
        created.append((player_cpu_request, player_memory_request))

    monkeypatch.setattr(kubernetes_runner, "_create_player_pod", create_player_pod)
    job = SimpleNamespace(
        players=[SimpleNamespace(image="paintbot:latest", run=[], env={})],
        results_schema={},
    )

    kubernetes_runner._run_kubernetes_episode(job, artifacts, timeout_seconds=1.0)

    assert created == [("2", "2Gi")]


def test_create_player_pod_injects_policy_secret_env(monkeypatch):
    created: dict[str, object] = {}
    core_v1 = SimpleNamespace(
        create_namespaced_pod=lambda *, namespace, body: created.update({"namespace": namespace, "body": body})
    )
    monkeypatch.setenv("COWORLD_WORKLOAD_TYPE", "jobs")
    monkeypatch.setenv("COWORLD_CAPACITY_TYPE", "on-demand")
    monkeypatch.setenv("COWORLD_BEDROCK_REGION", "us-east-1")
    player = PlayerLaunchSpec(
        image="paintbot:latest",
        run=(),
        env={
            "PUBLIC_SETTING": "visible",
            "ANTHROPIC_API_KEY": "placeholder",
            "BEDROCK_MODEL": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
        },
    )

    kubernetes_runner._create_player_pod(
        core_v1,
        "jobs",
        "job-player-0",
        0,
        "slot-token",
        player,
        {
            "ANTHROPIC_API_KEY": "sk-ant-test",
            "USE_BEDROCK": "true",
            "BEDROCK_MODEL": "us.amazon.nova-micro-v1:0",
        },
        "job-id",
        "game-service",
        "2",
        "2Gi",
        [],
    )

    pod = created["body"]
    container = pod.spec.containers[0]
    env = {env_var.name: env_var.value for env_var in container.env}
    assert env["PUBLIC_SETTING"] == "visible"
    assert env["ANTHROPIC_API_KEY"] == "sk-ant-test"
    assert env["USE_BEDROCK"] == "true"
    assert env["BEDROCK_MODEL"] == "us.amazon.nova-micro-v1:0"
    assert env["AWS_REGION"] == "us-east-1"
    assert env["AWS_DEFAULT_REGION"] == "us-east-1"
    assert env["COWORLD_PLAYER_WS_URL"] == "ws://game-service:8080/player?slot=0&token=slot-token"
    assert env["COGAMES_ENGINE_WS_URL"] == "ws://game-service:8080/player?slot=0&token=slot-token"
    # No PLAYER_ARTIFACT_UPLOAD_URLS set, so the player gets no artifact upload URL.
    assert "COWORLD_PLAYER_ARTIFACT_UPLOAD_URL" not in env
    assert container.resources.requests == {"cpu": "2", "memory": "2Gi"}
    assert pod.metadata.annotations == {"karpenter.sh/do-not-disrupt": "true"}
    assert pod.spec.node_selector == {"workload-type": "jobs", "karpenter.sh/capacity-type": "on-demand"}
    assert pod.spec.service_account_name == "episode-runner"


def test_create_player_pod_forwards_artifact_upload_url_for_its_slot(monkeypatch):
    created: dict[str, object] = {}
    core_v1 = SimpleNamespace(create_namespaced_pod=lambda *, namespace, body: created.update({"body": body}))
    monkeypatch.setenv(
        "PLAYER_ARTIFACT_UPLOAD_URLS",
        '{"0": "https://s3.example/put/policy_artifact_0.zip", "1": "https://s3.example/put/policy_artifact_1.zip"}',
    )
    player = PlayerLaunchSpec(image="paintbot:latest", run=(), env={})

    kubernetes_runner._create_player_pod(
        core_v1,
        "jobs",
        "job-player-1",
        1,
        "slot-token",
        player,
        {},
        "job-id",
        "game-service",
        "2",
        "2Gi",
        [],
    )

    env = {env_var.name: env_var.value for env_var in created["body"].spec.containers[0].env}
    assert env["COWORLD_PLAYER_ARTIFACT_UPLOAD_URL"] == "https://s3.example/put/policy_artifact_1.zip"


def test_create_player_pod_tags_bedrock_request_metadata_with_slot(monkeypatch):
    created: dict[str, object] = {}
    core_v1 = SimpleNamespace(create_namespaced_pod=lambda *, namespace, body: created.update({"body": body}))
    monkeypatch.setenv(
        "BEDROCK_REQUEST_METADATA",
        '{"coworld_id": "cow_abc", "coworld": "paintarena", "episode_id": "job-id"}',
    )
    player = PlayerLaunchSpec(image="paintbot:latest", run=(), env={})

    kubernetes_runner._create_player_pod(
        core_v1, "jobs", "job-player-1", 1, "slot-token", player, {}, "job-id", "game-service", "2", "2Gi", []
    )

    env = {env_var.name: env_var.value for env_var in created["body"].spec.containers[0].env}
    # The worker forwards the coworld/episode base and adds this pod's slot.
    assert json.loads(env["BEDROCK_REQUEST_METADATA"]) == {
        "coworld_id": "cow_abc",
        "coworld": "paintarena",
        "episode_id": "job-id",
        "slot": "1",
    }


def test_create_player_pod_omits_bedrock_request_metadata_when_unset(monkeypatch):
    created: dict[str, object] = {}
    core_v1 = SimpleNamespace(create_namespaced_pod=lambda *, namespace, body: created.update({"body": body}))
    monkeypatch.delenv("BEDROCK_REQUEST_METADATA", raising=False)
    player = PlayerLaunchSpec(image="paintbot:latest", run=(), env={})

    kubernetes_runner._create_player_pod(
        core_v1, "jobs", "job-player-0", 0, "slot-token", player, {}, "job-id", "game-service", "2", "2Gi", []
    )

    env = {env_var.name: env_var.value for env_var in created["body"].spec.containers[0].env}
    assert "BEDROCK_REQUEST_METADATA" not in env


def test_kubernetes_runner_uses_direct_player_urls_without_address():
    assert kubernetes_runner._player_client_url(1, "slot-token") == (
        "http://127.0.0.1:8080/client/player?slot=1&token=slot-token"
    )
    assert kubernetes_runner._player_service_ws_url("game-service", 1, "slot-token") == (
        "ws://game-service:8080/player?slot=1&token=slot-token"
    )


def test_run_from_env_writes_error_info_on_failure(monkeypatch, tmp_path):
    events: list[str] = []

    monkeypatch.setenv("COWORLD_WORKDIR", str(tmp_path))
    monkeypatch.setattr(kubernetes_runner, "_start_worker_health_server", lambda port: None)
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


def test_write_error_info_marks_failure_as_crash(monkeypatch, tmp_path):
    error_dest = tmp_path / "error_info.json"
    monkeypatch.setenv("ERROR_INFO_URI", error_dest.as_uri())

    kubernetes_runner._write_error_info(RuntimeError("Game container exited with code 1"))

    error_info = json.loads(error_dest.read_text(encoding="utf-8"))
    assert error_info["error_type"] == "crash"
    assert error_info["failed_policy_index"] is None
    assert "Game container exited with code 1" in error_info["message"]


def test_write_error_info_marks_player_pod_failure_as_policy_error(monkeypatch, tmp_path):
    error_dest = tmp_path / "error_info.json"
    monkeypatch.setenv("ERROR_INFO_URI", error_dest.as_uri())

    kubernetes_runner._write_error_info(kubernetes_runner.PlayerPodFailure(3, "player pod failed"))

    error_info = json.loads(error_dest.read_text(encoding="utf-8"))
    assert error_info["error_type"] == "policy_error"
    assert error_info["failed_policy_index"] == 3
    assert error_info["message"] == "player pod failed"


def test_write_error_info_marks_timeout_as_game_timeout(monkeypatch, tmp_path):
    error_dest = tmp_path / "error_info.json"
    monkeypatch.setenv("ERROR_INFO_URI", error_dest.as_uri())

    kubernetes_runner._write_error_info(TimeoutError("Timed out waiting for game container"))

    error_info = json.loads(error_dest.read_text(encoding="utf-8"))
    assert error_info["error_type"] == "game_timeout"
    assert error_info["failed_policy_index"] is None
    assert "Timed out waiting for game container" in error_info["message"]


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
        "2",
        "2Gi",
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

    monkeypatch.setattr(kubernetes_runner, "_start_worker_health_server", lambda port: None)
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
        assert "policy_agent_0.log" in names
        assert "policy_agent_1.log" in names
        assert zf.read("game.stdout.log").decode() == "game crashed with segfault"
        assert zf.read("policy_agent_0.log").decode() == "player 0 timeout waiting for server"

    # Verify per-policy logs were uploaded individually
    assert policy0_dest.read_text(encoding="utf-8") == "player 0 timeout waiting for server"
    assert policy1_dest.read_text(encoding="utf-8") == "player 1 connection refused"


def test_worker_health_server_accepts_connections_until_socket_closes():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    kubernetes_runner._start_worker_health_server(port)

    with socket.create_connection(("127.0.0.1", port), timeout=2) as conn:
        assert conn.fileno() >= 0
