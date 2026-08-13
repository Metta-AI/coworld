import asyncio
import json
import os
import socket
import subprocess
import sys
import threading
import time
import zipfile
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from kubernetes.client import Configuration
from kubernetes.client.rest import ApiException
from urllib3.exceptions import MaxRetryError, ResponseError

from coworld.runner import io as runner_io
from coworld.runner import kubernetes_runner
from coworld.runner import runner as runner_module
from coworld.runner.bedrock_sidecar_wiring import (
    BEDROCK_PROMPT_PREFIX_CONTROL_CONFIG_MAP_NAME,
    BEDROCK_PROMPT_PREFIX_ENABLED_PATH,
    BEDROCK_SIDECAR_CONTAINER_NAME,
    BEDROCK_SIDECAR_TOKEN_FILE,
    BEDROCK_SIDECAR_TOKEN_VOLUME_NAME,
)
from coworld.runner.kubernetes_runner import (
    _collect_logs,
    _player_image_pull_policy,
    _upload_outputs,
    _wait_for_episode_artifacts,
)
from coworld.runner.phase_timings import EpisodePhaseTimings
from coworld.runner.runner import EpisodeArtifacts, EpisodeRunSpec, PlayerLaunchSpec, RunnableLaunchSpec
from coworld.types import CoworldEpisodeJobSpec, CoworldHumanPlayerSpec


def test_legacy_run_command_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["kubernetes_runner", "run"])

    with pytest.raises(SystemExit, match="2"):
        kubernetes_runner.main()


@pytest.fixture(autouse=True)
def _player_service_wait_env(monkeypatch):
    monkeypatch.setenv("COWORLD_COORDINATOR_IMAGE", "coworld-coordinator:latest")
    monkeypatch.setenv("COWORLD_TIMEOUT_SECONDS", "60")
    monkeypatch.setenv(
        "BEDROCK_REQUEST_METADATA",
        '{"episode_request_id":"11111111-1111-1111-1111-111111111111","image_digest":"sha256:game",'
        '"job_request_id":"22222222-2222-2222-2222-222222222222","metadata_origin":"dispatcher",'
        '"role":"game","schema_version":"1","slot":"game","source":"coworld_episode"}',
    )


def test_load_incluster_config_sets_retries_without_rewriting_auth(monkeypatch):
    # kubernetes>=36.0.2 owns bearer-token handling (api_key['BearerToken'] plus
    # a refresh hook that rewrites it on token rotation). Setting .retries for 429
    # backoff is fine, but rewriting api_key / api_key_prefix breaks the refreshed
    # header. Regression test for the 2026-07-06 prod 401 outage.
    loaded = Configuration()
    loaded.api_key = {"BearerToken": "sa-token"}
    loaded.api_key_prefix = {"BearerToken": "Bearer"}

    load_calls: list[bool] = []
    saved: list[Configuration] = []

    monkeypatch.setattr(kubernetes_runner.config, "load_incluster_config", lambda: load_calls.append(True))
    monkeypatch.setattr(kubernetes_runner.client.Configuration, "get_default_copy", lambda: loaded)
    monkeypatch.setattr(kubernetes_runner.client.Configuration, "set_default", lambda c: saved.append(c))

    kubernetes_runner._load_incluster_config()

    assert load_calls == [True]
    assert saved == [loaded]
    # Retries set for 429 backoff...
    retries = loaded.retries
    assert retries is not None
    assert 429 in retries.status_forcelist
    assert retries.respect_retry_after_header is True
    # ...but the auth fields the refresh hook manages are untouched.
    assert loaded.api_key == {"BearerToken": "sa-token"}
    assert loaded.api_key_prefix == {"BearerToken": "Bearer"}


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
    last_exit_code: int | None = None,
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
        last_state=SimpleNamespace(
            terminated=SimpleNamespace(exit_code=last_exit_code, reason=reason, message=message)
            if last_exit_code is not None
            else None,
        ),
    )


class _FakeLogCoreV1:
    def __init__(
        self,
        statuses: dict[str, list],
        missing_pods: set[str] | None = None,
        log_errors: dict[tuple[str, str], Exception] | None = None,
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


def _declare_game_player_failure(artifacts: EpisodeArtifacts, *, slot: int, message: str) -> None:
    artifacts.player_failure_path.write_text(
        runner_io.GamePlayerFailure(
            message=message,
            failed_policy_index=slot,
        ).model_dump_json(),
        encoding="utf-8",
    )


def test_upload_outputs_uploads_raw_replay_bytes(tmp_path, monkeypatch):
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
    assert content_type == "application/octet-stream"
    assert replay_bytes == replay_payload
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


def test_player_image_pull_policy_uses_ifnotpresent_for_digest(monkeypatch):
    monkeypatch.delenv("COWORLD_PLAYER_IMAGE_PULL_POLICY", raising=False)
    assert _player_image_pull_policy("public.ecr.aws/x/paintbot@sha256:abc123") == "IfNotPresent"


def test_player_image_pull_policy_uses_always_for_mutable_tag(monkeypatch):
    monkeypatch.delenv("COWORLD_PLAYER_IMAGE_PULL_POLICY", raising=False)
    assert _player_image_pull_policy("public.ecr.aws/x/paintbot:latest") == "Always"


def test_player_image_pull_policy_env_override_wins(monkeypatch):
    monkeypatch.setenv("COWORLD_PLAYER_IMAGE_PULL_POLICY", "IfNotPresent")
    assert _player_image_pull_policy("public.ecr.aws/x/paintbot:latest") == "IfNotPresent"


def test_require_http_ok_accepts_replay_client_redirect(monkeypatch):
    class RedirectResponse:
        status_code = 307

        def raise_for_status(self):
            raise AssertionError("redirect should be accepted")

    monkeypatch.setattr(runner_module.httpx, "get", lambda _url, timeout: RedirectResponse())

    runner_module._require_http_ok("http://example.test/client/replay", allow_redirect=True)


def test_require_http_ok_reports_game_contract_violation(monkeypatch):
    url = "http://example.test/client/global"

    class ErrorResponse:
        status_code = 500

        def raise_for_status(self):
            request = runner_module.httpx.Request("GET", url)
            response = runner_module.httpx.Response(500, request=request)
            raise runner_module.httpx.HTTPStatusError("server error", request=request, response=response)

    monkeypatch.setattr(runner_module.httpx, "get", lambda _url, timeout: ErrorResponse())

    with pytest.raises(runner_io.RunnerEpisodeError) as exc_info:
        runner_module._require_http_ok(url)

    assert exc_info.value.error_type == "game_contract_violation"


def test_require_replay_message_reports_replay_unloadable(monkeypatch):
    def fail_connect(*_args, **_kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr(runner_module.websockets, "connect", fail_connect)

    with pytest.raises(runner_io.RunnerEpisodeError) as exc_info:
        asyncio.run(runner_module._require_replay_message("ws://example.test/replay", timeout_seconds=1))

    assert exc_info.value.error_type == "replay_unloadable"


def test_require_global_message_blames_player_when_player_already_failed(monkeypatch):
    # A player that crashes before the game emits its first global message starves
    # the /global socket. The connect failure must be attributed to the player
    # (player_error, with the slot), not the game contract.
    def fail_connect(*_args, **_kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr(runner_module.websockets, "connect", fail_connect)

    def probe() -> None:
        raise runner_io.RunnerEpisodeError(
            "Player container exited with status 1.",
            error_type="player_error",
            failed_policy_index=2,
        )

    with pytest.raises(runner_io.RunnerEpisodeError) as exc_info:
        asyncio.run(
            runner_module._require_global_message(
                "ws://example.test/global", timeout_seconds=1, on_connect_failure=probe
            )
        )

    assert exc_info.value.error_type == "player_error"
    assert exc_info.value.failed_policy_index == 2


def test_require_global_message_blames_game_contract_when_players_healthy(monkeypatch):
    # If no player has failed, a stalled /global socket is genuinely the game's fault.
    def fail_connect(*_args, **_kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr(runner_module.websockets, "connect", fail_connect)

    with pytest.raises(runner_io.RunnerEpisodeError) as exc_info:
        asyncio.run(
            runner_module._require_global_message(
                "ws://example.test/global", timeout_seconds=1, on_connect_failure=lambda: None
            )
        )

    assert exc_info.value.error_type == "game_contract_violation"


@pytest.mark.parametrize(
    ("episode_timeout_seconds", "startup_timeout_seconds", "expected_timeout_seconds"),
    [
        (5.0, runner_module.DEFAULT_RUNTIME_STARTUP_TIMEOUT_SECONDS, 5.0),
        (120.0, runner_module.DEFAULT_RUNTIME_STARTUP_TIMEOUT_SECONDS, 10.0),
        (120.0, runner_module.LOBBY_RUNTIME_STARTUP_TIMEOUT_SECONDS, 60.0),
    ],
)
def test_require_global_message_uses_the_selected_startup_timeout(
    monkeypatch, episode_timeout_seconds, startup_timeout_seconds, expected_timeout_seconds
):
    events: list[tuple[str, int]] = []

    class GlobalWebSocket:
        async def __aenter__(self):
            events.append(("viewer connected", threading.get_ident()))
            return self

        async def __aexit__(self, *_args):
            return None

        async def recv(self):
            events.append(("global message", threading.get_ident()))
            return b"frame"

    observed_timeouts: list[float] = []

    async def wait_for(awaitable, *, timeout):
        observed_timeouts.append(timeout)
        return await awaitable

    monkeypatch.setattr(runner_module.websockets, "connect", lambda *_args, **_kwargs: GlobalWebSocket())
    monkeypatch.setattr(runner_module.asyncio, "wait_for", wait_for)

    asyncio.run(
        runner_module._require_global_message(
            "ws://example.test/global",
            timeout_seconds=episode_timeout_seconds,
            startup_timeout_seconds=startup_timeout_seconds,
            on_connected=lambda: events.append(("players started", threading.get_ident())),
        )
    )

    assert observed_timeouts == [expected_timeout_seconds]
    assert [event for event, _thread_id in events] == ["viewer connected", "players started", "global message"]
    assert events[1][1] != events[0][1]


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
    assert f"{runner_module.PLAYER_FAILURE_ENV_VAR}=file:///coworld/player_failure.json" in env_values
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


def test_run_episode_containers_adds_fixed_extra_local_ports(tmp_path, monkeypatch):
    commands: list[list[str]] = []

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

    def fake_popen(command, **_kwargs):
        commands.append(command)
        return FakeProcess()

    monkeypatch.setattr(runner_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        runner_module.subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(command, 0),
    )

    runner_module.run_episode_containers(
        EpisodeRunSpec(
            game=RunnableLaunchSpec(
                image="game:latest",
                env={runner_module.LOCAL_EXTRA_PORTS_ENV_VAR: "3724:3724,8085:8085"},
            ),
            players=[],
            tokens=[],
            artifacts=EpisodeArtifacts.create(tmp_path),
            timeout_seconds=1,
            container_prefix="coworld-run",
        ),
        verify_replay=False,
    )

    game_command = commands[0]
    assert _docker_publish_values(game_command) == [
        "127.0.0.1:12345:8080",
        "127.0.0.1:3724:3724",
        "127.0.0.1:8085:8085",
    ]
    assert _env_value(game_command, "COWORLD_LOCAL_PORT_3724") == "127.0.0.1:3724"
    assert _env_value(game_command, "COWORLD_LOCAL_PORT_8085") == "127.0.0.1:8085"
    local_ports = _env_value(game_command, runner_module.LOCAL_PORTS_JSON_ENV_VAR)
    assert local_ports is not None
    assert json.loads(local_ports) == {
        "3724": {"host": "127.0.0.1", "port": 3724},
        "8085": {"host": "127.0.0.1", "port": 8085},
    }


def test_run_episode_containers_allocates_dynamic_extra_local_ports(tmp_path, monkeypatch):
    commands: list[list[str]] = []
    free_ports = iter([12345, 41000, 41001])

    class FakeProcess:
        def poll(self):
            return None

    async def noop_async(*_args, **_kwargs):
        return None

    monkeypatch.setattr(runner_module, "_free_local_port", lambda: next(free_ports))
    monkeypatch.setattr(runner_module.secrets, "token_hex", lambda _bytes: "session-1")
    monkeypatch.setattr(runner_module, "_wait_for_health", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(runner_module, "_require_http_ok", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(runner_module, "_require_bad_player_rejected", noop_async)
    monkeypatch.setattr(runner_module, "_require_global_message", noop_async)
    monkeypatch.setattr(runner_module, "_wait_for_game_exit", lambda *_args, **_kwargs: None)

    def fake_popen(command, **_kwargs):
        commands.append(command)
        return FakeProcess()

    monkeypatch.setattr(runner_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        runner_module.subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(command, 0),
    )

    runner_module.run_episode_containers(
        EpisodeRunSpec(
            game=RunnableLaunchSpec(
                image="game:latest",
                env={runner_module.LOCAL_EXTRA_PORTS_ENV_VAR: "3724:0,8085"},
            ),
            players=[],
            tokens=[],
            artifacts=EpisodeArtifacts.create(tmp_path),
            timeout_seconds=1,
            container_prefix="coworld-run",
        ),
        verify_replay=False,
    )

    game_command = commands[0]
    assert _docker_publish_values(game_command) == [
        "127.0.0.1:12345:8080",
        "127.0.0.1:41000:3724",
        "127.0.0.1:41001:8085",
    ]
    assert _env_value(game_command, "COWORLD_LOCAL_PORT_3724") == "127.0.0.1:41000"
    assert _env_value(game_command, "COWORLD_LOCAL_PORT_8085") == "127.0.0.1:41001"


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("0:3724", "invalid container port 0"),
        ("3724:70000", "invalid host port 70000"),
        ("3724:3724,3724:3725", "container port 3724"),
        ("3724:3724,8085:3724", "host port 3724"),
        ("8080:8080", "container port 8080"),
        ("3724/udp", "only supports tcp"),
        ("abc:3724", "non-numeric container port"),
    ],
)
def test_resolve_local_extra_ports_rejects_invalid_or_duplicate_mappings(value, message):
    with pytest.raises(ValueError, match=message):
        runner_module.resolve_local_extra_ports(
            {runner_module.LOCAL_EXTRA_PORTS_ENV_VAR: value},
            reserved_host_ports={12345},
            allocate_port=lambda: 41000,
        )


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


def test_run_episode_containers_verifies_raw_replay_uri(tmp_path, monkeypatch):
    commands: list[list[str]] = []
    mounted_replay_bytes: list[bytes] = []
    free_ports = iter([12345, 3724, 41000])
    artifacts = EpisodeArtifacts.create(tmp_path)
    replay_payload = b"\x00crewrift-replay-bytes\xff"
    artifacts.replay_path.write_bytes(replay_payload)

    class FakeProcess:
        def poll(self):
            return None

    async def noop_async(*_args, **_kwargs):
        return None

    monkeypatch.setattr(runner_module, "_free_local_port", lambda: next(free_ports))
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
            mounted_replay_bytes.append((mounted_replay_dir / "replay").read_bytes())
        return FakeProcess()

    monkeypatch.setattr(runner_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        runner_module.subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(command, 0),
    )

    runner_module.run_episode_containers(
        EpisodeRunSpec(
            game=RunnableLaunchSpec(
                image="game:latest",
                env={runner_module.LOCAL_EXTRA_PORTS_ENV_VAR: "3724:3724"},
            ),
            players=[],
            tokens=[],
            artifacts=artifacts,
            timeout_seconds=1,
            container_prefix="coworld-run",
        ),
        verify_replay=True,
    )

    _game_command, replay_command = commands
    assert _docker_publish_values(replay_command) == [
        "127.0.0.1:41000:8080",
        "127.0.0.1:3724:3724",
    ]
    assert f"{runner_module.REPLAY_LOAD_ENV_VAR}=file:///coworld-replay/replay" in replay_command
    assert mounted_replay_bytes[0] == replay_payload


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
        player_count=0,
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
        player_count=0,
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
        player_count=0,
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
            "job-player-0": [_container_status("player", exit_code=0, reason="Completed")],
        },
    )

    with pytest.raises(runner_io.RunnerEpisodeError, match="replay") as exc_info:
        _wait_for_episode_artifacts(
            artifacts,
            core_v1,
            "default",
            "game-pod",
            ["job-player-0"],
            player_count=1,
            timeout_seconds=1.0,
            require_replay=True,
        )

    assert exc_info.value.error_type == "replay_missing"


def test_wait_for_episode_artifacts_reports_results_missing_when_game_exits_without_results(tmp_path):
    artifacts = EpisodeArtifacts.create(tmp_path)
    core_v1 = _FakeCoreV1(game_exit_codes=[0])

    with pytest.raises(runner_io.RunnerEpisodeError, match="results.json") as exc_info:
        _wait_for_episode_artifacts(
            artifacts,
            core_v1,
            "default",
            "game-pod",
            [],
            player_count=0,
            timeout_seconds=1.0,
            require_replay=False,
        )

    assert exc_info.value.error_type == "results_missing"


def test_wait_for_episode_artifacts_sees_failure_written_during_clean_game_exit(tmp_path):
    artifacts = EpisodeArtifacts.create(tmp_path)

    class DeclaringCoreV1:
        def read_namespaced_pod(self, *, name: str, namespace: str):
            _declare_game_player_failure(artifacts, slot=0, message="player failed during shutdown")
            return SimpleNamespace(
                status=SimpleNamespace(
                    container_statuses=[
                        SimpleNamespace(
                            name="game",
                            state=SimpleNamespace(terminated=SimpleNamespace(exit_code=0)),
                        )
                    ]
                )
            )

    with pytest.raises(runner_io.RunnerEpisodeError, match="failed during shutdown") as exc_info:
        _wait_for_episode_artifacts(
            artifacts,
            DeclaringCoreV1(),
            "default",
            "game-pod",
            ["job-player-0"],
            player_count=1,
            timeout_seconds=1.0,
            require_replay=False,
        )

    assert exc_info.value.error_type == "player_error"
    assert exc_info.value.failed_policy_index == 0


def test_wait_for_episode_artifacts_reports_game_unhealthy_when_game_exits_nonzero(tmp_path):
    artifacts = EpisodeArtifacts.create(tmp_path)
    core_v1 = _FakeCoreV1(game_exit_codes=[42])

    with pytest.raises(runner_io.RunnerEpisodeError, match="42") as exc_info:
        _wait_for_episode_artifacts(
            artifacts,
            core_v1,
            "default",
            "game-pod",
            [],
            player_count=0,
            timeout_seconds=1.0,
            require_replay=False,
        )

    assert exc_info.value.error_type == "game_unhealthy"


def test_wait_for_health_reports_game_unhealthy_when_game_exits_nonzero():
    core_v1 = _FakeCoreV1(game_exit_codes=[2])

    with pytest.raises(runner_io.RunnerEpisodeError, match="2") as exc_info:
        kubernetes_runner._wait_for_health(core_v1, "default", "game-pod", timeout_seconds=1.0)

    assert exc_info.value.error_type == "game_unhealthy"


def test_validate_results_file_reports_results_malformed(tmp_path):
    results_path = tmp_path / "results.json"
    results_path.write_text('{"score": "not-a-number"}', encoding="utf-8")

    with pytest.raises(runner_io.RunnerEpisodeError, match="results_schema") as exc_info:
        runner_module._validate_results_file(
            results_path,
            {"type": "object", "properties": {"score": {"type": "number"}}},
        )

    assert exc_info.value.error_type == "results_malformed"


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
    core_v1 = _FakeCoreV1(player_statuses={"job-player-0": [player_status]})

    with pytest.raises(kubernetes_runner.PlayerPodFailure) as exc_info:
        _wait_for_episode_artifacts(
            artifacts,
            core_v1,
            "default",
            "game-pod",
            ["job-player-0"],
            player_count=1,
            timeout_seconds=0.01,
            require_replay=False,
        )

    assert exc_info.value.failed_policy_index == 0
    assert expected_message in str(exc_info.value)


def test_game_declared_player_failure_is_attributed(tmp_path):
    artifacts = EpisodeArtifacts.create(tmp_path)
    _declare_game_player_failure(
        artifacts,
        slot=3,
        message="RFC player slot 3 failed before completing its session",
    )

    with pytest.raises(runner_io.RunnerEpisodeError, match="slot 3") as exc_info:
        runner_module._raise_if_game_declared_player_failure(artifacts, (artifacts.results_path,), player_count=4)

    assert exc_info.value.error_type == "player_error"
    assert exc_info.value.failed_policy_index == 3


def test_game_player_failure_rejects_runner_error_type():
    with pytest.raises(ValueError):
        runner_io.GamePlayerFailure.model_validate(
            {
                "message": "player failed",
                "failed_policy_index": 0,
                "error_type": "player_error",
            }
        )


def test_game_declared_player_failure_rejects_out_of_range_slot(tmp_path):
    artifacts = EpisodeArtifacts.create(tmp_path)
    _declare_game_player_failure(artifacts, slot=2, message="invalid player slot")

    with pytest.raises(runner_io.RunnerEpisodeError, match="episode has 2 players") as exc_info:
        runner_module._raise_if_game_declared_player_failure(artifacts, (artifacts.results_path,), player_count=2)

    assert exc_info.value.error_type == "game_contract_violation"
    assert exc_info.value.failed_policy_index is None


def test_outputs_written_while_reading_malformed_player_failure_win(tmp_path, monkeypatch):
    artifacts = EpisodeArtifacts.create(tmp_path)
    artifacts.player_failure_path.write_text("not-json", encoding="utf-8")
    read_text = Path.read_text

    def read_player_failure(path: Path, *args, **kwargs) -> str:
        if path == artifacts.player_failure_path:
            artifacts.results_path.write_text("{}", encoding="utf-8")
        return read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_player_failure)

    runner_module._raise_if_game_declared_player_failure(artifacts, (artifacts.results_path,), player_count=1)


class _FakeGateCoreV1:
    """Read scripts repeat their last entry; None means the pod is missing."""

    def __init__(self, reads: dict[str, list]):
        self.reads = {name: list(entries) for name, entries in reads.items()}

    def read_namespaced_pod(self, *, name: str, namespace: str):
        entries = self.reads[name]
        entry = entries.pop(0) if len(entries) > 1 else entries[0]
        if entry is None:
            raise ApiException(status=404)
        return SimpleNamespace(status=SimpleNamespace(container_statuses=entry))


@pytest.fixture
def gate_clock(monkeypatch):
    clock = {"now": 0.0}
    monkeypatch.setattr(kubernetes_runner.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(
        kubernetes_runner.time, "sleep", lambda seconds: clock.__setitem__("now", clock["now"] + seconds)
    )
    return clock


def _run_player_start_gate(
    core_v1,
    *,
    pod_names: tuple[str, ...] = ("job-player-0",),
) -> None:
    kubernetes_runner._ensure_player_pods_started(
        core_v1,
        "default",
        pod_names,
        timeout_seconds=10.0,
    )


def test_ensure_player_pods_started_passes_when_every_player_started(gate_clock):
    core_v1 = _FakeGateCoreV1(
        reads={
            "job-player-0": [[_container_status("player", running=True)]],
            "job-player-1": [[_container_status("player", exit_code=0, reason="Completed")]],
        }
    )

    _run_player_start_gate(core_v1, pod_names=("job-player-0", "job-player-1"))


def test_ensure_player_pods_started_waits_for_a_late_starting_slot(gate_clock):
    # Kubernetes status may lag a process that already acquired its one-shot game slot. The
    # original pod must retain the full connection budget instead of being replaced halfway.
    waiting = [_container_status("player", waiting=True, reason="ContainerCreating")]
    core_v1 = _FakeGateCoreV1(
        reads={
            "job-player-0": [
                waiting,
                waiting,
                waiting,
                waiting,
                waiting,
                waiting,
                [_container_status("player", running=True)],
            ]
        }
    )

    _run_player_start_gate(core_v1)

    assert gate_clock["now"] == 6.0


@pytest.mark.parametrize("reason", sorted(kubernetes_runner._PLAYER_WAITING_POLICY_FAILURE_REASONS))
def test_ensure_player_pods_started_policy_failures_are_player_error_not_retried(gate_clock, reason: str):
    core_v1 = _FakeGateCoreV1(reads={"job-player-0": [[_container_status("player", waiting=True, reason=reason)]]})

    with pytest.raises(kubernetes_runner.PlayerPodFailure) as exc_info:
        _run_player_start_gate(core_v1)

    assert exc_info.value.failed_policy_index == 0
    assert reason in str(exc_info.value)


def test_ensure_player_pods_started_preserves_last_player_termination(gate_clock):
    core_v1 = _FakeGateCoreV1(
        reads={
            "job-player-0": [
                [_container_status("player", waiting=True, last_exit_code=1, reason="Error", message="policy crashed")]
            ]
        }
    )

    with pytest.raises(kubernetes_runner.PlayerPodFailure) as exc_info:
        _run_player_start_gate(core_v1)

    assert exc_info.value.failed_policy_index == 0
    assert "terminated with exit code 1" in str(exc_info.value)


def test_ensure_player_pods_started_counts_clean_last_termination_as_started(gate_clock):
    core_v1 = _FakeGateCoreV1(
        reads={"job-player-0": [[_container_status("player", waiting=True, last_exit_code=0, reason="Completed")]]}
    )

    _run_player_start_gate(core_v1)


@pytest.mark.parametrize(
    ("reads", "message"),
    [
        ([[_container_status("player", waiting=True, reason="ContainerCreating")]], "slot 0: ContainerCreating"),
        ([None], "pod job-player-0 not found"),
    ],
)
def test_ensure_player_pods_started_times_out_typed(gate_clock, reads, message):
    core_v1 = _FakeGateCoreV1(reads={"job-player-0": reads})

    with pytest.raises(runner_io.RunnerEpisodeError) as exc_info:
        _run_player_start_gate(core_v1)

    assert exc_info.value.error_type == "player_never_started"
    assert message in str(exc_info.value)


def test_ensure_player_pods_started_treats_missing_started_pod_as_inconclusive(gate_clock):
    # A started pod that is later reaped must not be re-derived as never-started — that was the
    # bug that failed 30+ minute matches as player_never_started after terminated-pod GC.
    core_v1 = _FakeGateCoreV1(
        reads={
            "job-player-0": [[_container_status("player", running=True)], None],
            "job-player-1": [
                [_container_status("player", waiting=True, reason="ContainerCreating")],
                [_container_status("player", running=True)],
            ],
        }
    )

    _run_player_start_gate(core_v1, pod_names=("job-player-0", "job-player-1"))


def test_ensure_player_pods_started_rejects_started_player_crash_while_another_starts(gate_clock):
    core_v1 = _FakeGateCoreV1(
        reads={
            "job-player-0": [
                [_container_status("player", running=True)],
                [_container_status("player", exit_code=1, reason="Error", message="policy crashed")],
            ],
            "job-player-1": [
                [_container_status("player", waiting=True, reason="ContainerCreating")],
                [_container_status("player", running=True)],
            ],
        }
    )

    with pytest.raises(kubernetes_runner.PlayerPodFailure, match="policy crashed") as exc_info:
        _run_player_start_gate(core_v1, pod_names=("job-player-0", "job-player-1"))

    assert exc_info.value.failed_policy_index == 0


def test_player_pod_slot_requires_the_production_name_shape():
    assert kubernetes_runner._player_pod_slot("episode-player-3") == 3

    with pytest.raises(ValueError, match="does not end in '-player-<slot>'"):
        kubernetes_runner._player_pod_slot("player-3")


def test_wait_for_players_to_complete_observes_clean_process_completion():
    statuses = iter(
        [
            [_container_status("player", running=True)],
            [_container_status("player", exit_code=0, reason="Completed")],
        ]
    )

    class SequencedCoreV1:
        def read_namespaced_pod(self, *, name: str, namespace: str):
            return SimpleNamespace(status=SimpleNamespace(container_statuses=next(statuses)))

    kubernetes_runner._wait_for_players_to_complete(
        SequencedCoreV1(),
        "default",
        ["job-player-0"],
        timeout_seconds=1.0,
    )


def test_wait_for_players_to_complete_rejects_late_player_crash():
    statuses = iter(
        [
            [_container_status("player", running=True)],
            [_container_status("player", exit_code=1, reason="Error", message="policy crashed")],
        ]
    )

    class SequencedCoreV1:
        def read_namespaced_pod(self, *, name: str, namespace: str):
            return SimpleNamespace(status=SimpleNamespace(container_statuses=next(statuses)))

    with pytest.raises(kubernetes_runner.PlayerPodFailure, match="policy crashed") as exc_info:
        kubernetes_runner._wait_for_players_to_complete(
            SequencedCoreV1(),
            "default",
            ["job-player-0"],
            timeout_seconds=1.0,
        )

    assert exc_info.value.failed_policy_index == 0


def test_post_artifact_player_check_treats_missing_pod_as_inconclusive():
    core_v1 = _FakeGateCoreV1(reads={"job-player-0": [None]})

    kubernetes_runner._raise_if_player_pod_failed(core_v1, "default", ["job-player-0"])


def test_wait_for_episode_artifacts_ignores_clean_player_exit_on_timeout(tmp_path):
    artifacts = EpisodeArtifacts.create(tmp_path)
    core_v1 = _FakeCoreV1(
        player_statuses={
            "job-player-0": [_container_status("player", exit_code=0, reason="Completed")],
        }
    )

    with pytest.raises(runner_io.RunnerEpisodeError, match="results") as exc_info:
        _wait_for_episode_artifacts(
            artifacts,
            core_v1,
            "default",
            "game-pod",
            ["job-player-0"],
            player_count=1,
            timeout_seconds=0.01,
            require_replay=False,
        )

    assert exc_info.value.error_type == "episode_timeout"


def test_wait_for_episode_artifacts_ignores_player_pods(tmp_path, monkeypatch):
    # Regression: episode success depends only on the game container. A player pod
    # exiting (even cleanly) or disappearing must not fail the episode. Previously a
    # player pod that exited 0 before results were written was reported as a
    # player_error and failed the entire round.
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
        ["job-player-0"],
        player_count=1,
        timeout_seconds=1.0,
        require_replay=True,
    )

    assert artifacts.replay_path.exists()


def test_collect_logs_records_marker_for_player_pods_that_never_started(tmp_path):
    artifacts = EpisodeArtifacts.create(tmp_path)
    core_v1 = _FakeLogCoreV1(
        {
            "job-player-0": [_container_status("player", waiting=True)],
            "job-player-1": [_container_status("player", running=True)],
        }
    )

    _collect_logs(
        core_v1,
        "default",
        "game-pod",
        ["job-player-0", "job-player-1"],
        artifacts,
    )

    assert artifacts.game_stdout_path.read_text(encoding="utf-8") == "game-pod game combined stdout stderr logs"
    assert artifacts.policy_log_path(0).read_text(encoding="utf-8") == (
        "No logs collected for pod job-player-0 container player: the player container never started.\n"
    )
    assert artifacts.policy_log_path(1).read_text(encoding="utf-8") == (
        "job-player-1 player combined stdout stderr logs"
    )
    assert core_v1.log_calls == [("game-pod", "game"), ("job-player-1", "player")]


def test_collect_logs_records_marker_for_missing_player_pods(tmp_path):
    # Regression for the hosted-episode observability gap: a player pod reaped before log
    # collection must leave an explanatory log artifact, not silently vanish from the
    # uploaded set (Asana 1217127622073619 / Metta-AI/coworld#31).
    artifacts = EpisodeArtifacts.create(tmp_path)
    core_v1 = _FakeLogCoreV1(
        {
            "game-pod": [],
            "job-player-1": [_container_status("player", running=True)],
        },
        missing_pods={"job-player-0"},
    )

    _collect_logs(
        core_v1,
        "default",
        "game-pod",
        ["job-player-0", "job-player-1"],
        artifacts,
    )

    assert artifacts.game_stdout_path.read_text(encoding="utf-8") == "game-pod game combined stdout stderr logs"
    assert artifacts.policy_log_path(0).read_text(encoding="utf-8") == (
        "No logs collected for pod job-player-0 container player: the pod was deleted before log collection.\n"
    )
    assert artifacts.policy_log_path(1).read_text(encoding="utf-8") == (
        "job-player-1 player combined stdout stderr logs"
    )
    assert core_v1.log_calls == [("game-pod", "game"), ("job-player-1", "player")]


def test_collect_logs_records_marker_when_player_log_read_404s(tmp_path):
    artifacts = EpisodeArtifacts.create(tmp_path)
    core_v1 = _FakeLogCoreV1(
        {
            "game-pod": [],
            "job-player-0": [_container_status("player", running=True)],
        },
        log_errors={("job-player-0", "player"): ApiException(status=404)},
    )

    _collect_logs(
        core_v1,
        "default",
        "game-pod",
        ["job-player-0"],
        artifacts,
    )

    assert artifacts.policy_log_path(0).read_text(encoding="utf-8") == (
        "No logs collected for pod job-player-0 container player: the pod was deleted before log collection.\n"
    )


def test_collect_logs_records_marker_when_game_log_read_404s(tmp_path):
    artifacts = EpisodeArtifacts.create(tmp_path)
    core_v1 = _FakeLogCoreV1(
        {
            "game-pod": [],
            "job-player-0": [_container_status("player", running=True)],
        },
        log_errors={("game-pod", "game"): ApiException(status=404)},
    )

    _collect_logs(
        core_v1,
        "default",
        "game-pod",
        ["job-player-0"],
        artifacts,
    )

    assert artifacts.game_stdout_path.read_text(encoding="utf-8") == (
        "No logs collected for pod game-pod container game: the pod was gone before log collection.\n"
    )
    assert artifacts.policy_log_path(0).read_text(encoding="utf-8") == (
        "job-player-0 player combined stdout stderr logs"
    )


def test_collect_logs_records_player_log_errors_without_failing(tmp_path):
    artifacts = EpisodeArtifacts.create(tmp_path)
    core_v1 = _FakeLogCoreV1(
        {
            "game-pod": [],
            "job-player-0": [_container_status("player", running=True)],
            "job-player-1": [_container_status("player", running=True)],
        },
        log_errors={("job-player-0", "player"): ApiException(status=500, reason="kubelet timeout")},
    )

    _collect_logs(
        core_v1,
        "default",
        "game-pod",
        ["job-player-0", "job-player-1"],
        artifacts,
    )

    assert artifacts.game_stdout_path.read_text(encoding="utf-8") == "game-pod game combined stdout stderr logs"
    assert "Failed to collect Kubernetes logs for pod job-player-0 container player" in artifacts.policy_log_path(
        0
    ).read_text(encoding="utf-8")
    assert artifacts.policy_log_path(1).read_text(encoding="utf-8") == (
        "job-player-1 player combined stdout stderr logs"
    )
    assert core_v1.log_calls == [
        ("game-pod", "game"),
        ("job-player-0", "player"),
        ("job-player-1", "player"),
    ]


def test_collect_logs_records_game_log_read_failures(tmp_path):
    artifacts = EpisodeArtifacts.create(tmp_path)
    core_v1 = _FakeLogCoreV1(
        {
            "game-pod": [],
            "job-player-0": [_container_status("player", running=True)],
        },
        log_errors={("game-pod", "game"): ApiException(status=500, reason="kubelet timeout")},
    )

    _collect_logs(
        core_v1,
        "default",
        "game-pod",
        ["job-player-0"],
        artifacts,
    )

    assert artifacts.game_stdout_path.read_text(encoding="utf-8").startswith(
        "Failed to collect Kubernetes logs for pod game-pod container game:"
    )
    assert artifacts.policy_log_path(0).read_text(encoding="utf-8") == (
        "job-player-0 player combined stdout stderr logs"
    )
    assert core_v1.log_calls == [("game-pod", "game"), ("job-player-0", "player")]


def test_collect_logs_records_kubernetes_transport_failures(tmp_path):
    artifacts = EpisodeArtifacts.create(tmp_path)
    transport_error = MaxRetryError(
        None,
        "/api/v1/namespaces/jobs/pods/job-player-0/log",
        ResponseError("too many 500 error responses"),
    )
    core_v1 = _FakeLogCoreV1(
        {
            "game-pod": [],
            "job-player-0": [_container_status("player", running=True)],
        },
        log_errors={("job-player-0", "player"): transport_error},
    )

    _collect_logs(
        core_v1,
        "default",
        "game-pod",
        ["job-player-0"],
        artifacts,
    )

    failure = artifacts.policy_log_path(0).read_text(encoding="utf-8")
    assert failure.startswith("Failed to collect Kubernetes logs for pod job-player-0 container player:")
    assert "too many 500 error responses" in failure


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


@pytest.mark.parametrize(
    ("game_config", "expected_player_start_timeout", "episode_tags", "expected_completion_waits"),
    [
        ({}, kubernetes_runner.DEFAULT_PLAYER_CONNECT_TIMEOUT_SECONDS, {}, []),
        (
            {"player_connect_timeout_seconds": 45},
            45.0,
            {"source": runner_module.CERTIFICATION_EPISODE_SOURCE},
            [("jobs", ["game-service-player-1"], runner_module.DEFAULT_PLAYER_EXIT_TIMEOUT_SECONDS)],
        ),
    ],
)
def test_run_kubernetes_episode_keeps_artifacts_authoritative_except_for_certification(
    monkeypatch,
    tmp_path,
    game_config,
    expected_player_start_timeout,
    episode_tags,
    expected_completion_waits,
):
    artifacts = EpisodeArtifacts.create(tmp_path)
    artifacts.results_path.write_text("{}", encoding="utf-8")
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"tokens": ["human-token", "policy-token"]}), encoding="utf-8")
    created: list[tuple[int, str, str, str]] = []
    startup_timeouts: list[float] = []
    player_start_timeouts: list[float] = []
    completion_waits: list[tuple[str, list[str], float]] = []
    pong_requirements: list[bool] = []

    async def noop_async(*_args, **_kwargs):
        return None

    async def record_global_startup_timeout(*_args, startup_timeout_seconds, on_connected, require_pong, **_kwargs):
        startup_timeouts.append(startup_timeout_seconds)
        pong_requirements.append(require_pong)
        on_connected()

    monkeypatch.setattr(kubernetes_runner, "STATE_PATH", state_path)
    clock = {"now": 100.0}
    monkeypatch.setattr(kubernetes_runner.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(kubernetes_runner, "_load_incluster_config", lambda: None)
    monkeypatch.setattr(kubernetes_runner.client, "CoreV1Api", lambda: object())
    monkeypatch.setattr(kubernetes_runner, "_create_game_service", lambda *_args: None)
    monkeypatch.setattr(
        kubernetes_runner, "_wait_for_health", lambda *_args, **_kwargs: clock.__setitem__("now", 120.0)
    )
    monkeypatch.setattr(kubernetes_runner, "_require_http_ok", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(kubernetes_runner, "_require_bad_player_rejected", noop_async)
    monkeypatch.setattr(kubernetes_runner, "_require_global_message", record_global_startup_timeout)
    monkeypatch.setattr(kubernetes_runner, "_wait_for_episode_artifacts", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(kubernetes_runner, "_validate_results_file", lambda *_args: None)
    monkeypatch.setattr(
        kubernetes_runner,
        "_raise_if_player_pod_failed",
        lambda *_args: pytest.fail("ordinary episode completion re-read player pod state after artifacts"),
    )
    monkeypatch.setattr(
        kubernetes_runner,
        "_wait_for_players_to_complete",
        lambda _core_v1, namespace, pod_names, *, timeout_seconds: completion_waits.append(
            (namespace, pod_names, timeout_seconds)
        ),
    )
    monkeypatch.setattr(
        kubernetes_runner,
        "_ensure_player_pods_started",
        lambda *_args, timeout_seconds, **_kwargs: player_start_timeouts.append(timeout_seconds),
    )
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
        slot,
        _token,
        _player,
        _policy_secret_env,
        _job_id,
        _service_name,
        player_cpu_request,
        player_memory_request,
        player_cpu_limit,
        _owner_references,
    ):
        created.append((slot, player_cpu_request, player_memory_request, player_cpu_limit))

    monkeypatch.setattr(kubernetes_runner, "_create_player_pod", create_player_pod)
    job = cast(
        CoworldEpisodeJobSpec,
        SimpleNamespace(
            players=[
                CoworldHumanPlayerSpec(type="human", token="private-browser-seat-token"),
                SimpleNamespace(image="paintbot:latest", run=[], env={}),
            ],
            game_config=game_config,
            results_schema={},
            episode_tags=episode_tags,
        ),
    )

    kubernetes_runner._run_kubernetes_episode(job, artifacts, timeout_seconds=600.0)

    assert created == [(1, "2", "2Gi", "")]
    assert startup_timeouts == [runner_module.LOBBY_RUNTIME_STARTUP_TIMEOUT_SECONDS]
    assert pong_requirements == [episode_tags.get("source") == runner_module.CERTIFICATION_EPISODE_SOURCE]
    assert player_start_timeouts == [expected_player_start_timeout]
    assert completion_waits == expected_completion_waits


def test_create_game_service_exposes_human_proxy_without_rerouting_policy_players(monkeypatch):
    created: dict[str, Any] = {}
    core_v1 = SimpleNamespace(
        create_namespaced_service=lambda *, namespace, body: created.update({"namespace": namespace, "body": body})
    )
    monkeypatch.setenv("COWORLD_HUMAN_PLAYER_PROXY_PORT", "8081")

    kubernetes_runner._create_game_service(core_v1, "jobs", "game-service", "job-id", [])

    service: Any = created["body"]
    ports = {port.name: port for port in service.spec.ports}
    assert ports["http"].port == 8080
    assert ports["http"].target_port == 8080
    assert ports["human-player"].port == 8081
    assert ports["human-player"].target_port == 8081


def test_create_player_pod_injects_policy_secret_env(monkeypatch):
    created: dict[str, Any] = {}
    core_v1 = SimpleNamespace(
        create_namespaced_pod=lambda *, namespace, body: created.update({"namespace": namespace, "body": body})
    )
    monkeypatch.setenv("COWORLD_WORKLOAD_TYPE", "jobs")
    monkeypatch.setenv("COWORLD_CAPACITY_TYPE", "on-demand")
    monkeypatch.setenv("COWORLD_BEDROCK_REGION", "us-east-1")
    monkeypatch.setenv("COWORLD_ID", "cow_11111111-1111-1111-1111-111111111111")
    monkeypatch.setenv("COWORLD_LEAGUE_ID", "league_44444444-4444-4444-4444-444444444444")
    monkeypatch.setenv("COWORLD_SOURCE", "xp_request")
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
            "BEDROCK_MODEL": "us.amazon.nova-micro-v1:0",
        },
        "job-id",
        "game-service",
        "2",
        "2Gi",
        "",
        [],
    )

    pod: Any = created["body"]
    container: Any = pod.spec.containers[0]
    assert [container.name for container in pod.spec.containers] == ["player"]
    env = {env_var.name: env_var.value for env_var in container.env}
    assert env["PUBLIC_SETTING"] == "visible"
    assert env["ANTHROPIC_API_KEY"] == "sk-ant-test"
    assert env["BEDROCK_MODEL"] == "us.amazon.nova-micro-v1:0"
    assert "AWS_ENDPOINT_URL_BEDROCK_RUNTIME" not in env
    assert env["COWORLD_PLAYER_WS_URL"] == "ws://game-service:8080/player?slot=0&token=slot-token"
    assert env["COGAMES_ENGINE_WS_URL"] == "ws://game-service:8080/player?slot=0&token=slot-token"
    # No PLAYER_ARTIFACT_UPLOAD_URLS set, so the player gets no artifact upload URL.
    assert "COWORLD_PLAYER_ARTIFACT_UPLOAD_URL" not in env
    assert container.resources.requests == {"cpu": "2", "memory": "2Gi"}
    assert pod.metadata.annotations == {"karpenter.sh/do-not-disrupt": "true"}
    assert pod.metadata.labels["job-id"] == "job-id"
    assert pod.metadata.labels["coworld-component"] == "player"
    # The AWS-facing spellings. Nothing in-cluster selects on these, so a silent drop would
    # only show up as a hole in the CUR cost allocation column -- pin them here instead.
    assert pod.metadata.labels["softmax.com/job-id"] == "job-id"
    assert pod.metadata.labels["coworld-player-slot"] == "0"
    # Cost-attribution identity forwarded by the dispatcher via the worker env.
    assert pod.metadata.labels["coworld-id"] == "cow_11111111-1111-1111-1111-111111111111"
    assert pod.metadata.labels["league-id"] == "league_44444444-4444-4444-4444-444444444444"
    assert pod.metadata.labels["coworld-source"] == "xp_request"
    assert pod.spec.node_selector == {"workload-type": "jobs", "karpenter.sh/capacity-type": "on-demand"}
    assert pod.spec.service_account_name is None
    assert pod.spec.volumes is None
    assert pod.spec.automount_service_account_token is None
    wait_for_game = pod.spec.init_containers[0]
    assert wait_for_game.name == "wait-for-game-service"
    assert wait_for_game.image == "coworld-coordinator:latest"
    wait_env = {env_var.name: env_var.value for env_var in wait_for_game.env}
    assert wait_env == {
        "COWORLD_GAME_HOST": "game-service",
        "COWORLD_GAME_PORT": "8080",
        "COWORLD_GAME_WAIT_TIMEOUT_SECONDS": "60",
    }


def test_create_player_pod_omits_attribution_labels_without_forwarded_env(monkeypatch):
    # League-less episodes get no COWORLD_LEAGUE_ID; a worker running without the
    # attribution env (e.g. dispatched before the dispatcher forwarded it) must not
    # stamp empty label values.
    created: dict[str, Any] = {}
    core_v1 = SimpleNamespace(
        create_namespaced_pod=lambda *, namespace, body: created.update({"namespace": namespace, "body": body})
    )
    monkeypatch.delenv("BEDROCK_SIDECAR_ENABLED", raising=False)
    monkeypatch.delenv("COWORLD_ID", raising=False)
    monkeypatch.delenv("COWORLD_LEAGUE_ID", raising=False)
    monkeypatch.delenv("COWORLD_SOURCE", raising=False)

    kubernetes_runner._create_player_pod(
        core_v1,
        "jobs",
        "job-player-0",
        0,
        "slot-token",
        PlayerLaunchSpec(image="paintbot:latest", run=(), env={}),
        {},
        "job-id",
        "game-service",
        "2",
        "2Gi",
        "",
        [],
    )

    labels = created["body"].metadata.labels
    assert "coworld-id" not in labels
    assert "league-id" not in labels
    assert "coworld-source" not in labels


def test_player_service_gate_waits_for_delayed_endpoint():
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]

    def make_service_ready() -> None:
        time.sleep(0.1)
        listener.listen()
        connection, _ = listener.accept()
        connection.close()
        listener.close()

    thread = threading.Thread(target=make_service_ready, daemon=True)
    thread.start()
    completed = subprocess.run(
        [sys.executable, "-c", kubernetes_runner._WAIT_FOR_GAME_SERVICE_SCRIPT],
        env={
            **os.environ,
            "COWORLD_GAME_HOST": "127.0.0.1",
            "COWORLD_GAME_PORT": str(port),
            "COWORLD_GAME_WAIT_TIMEOUT_SECONDS": "2",
        },
        check=False,
        timeout=3,
    )
    thread.join(timeout=1)

    assert completed.returncode == 0
    assert not thread.is_alive()


def test_player_service_gate_retries_transient_dns_failure():
    flaky_socket_setup = """
import socket

outcomes = iter([socket.gaierror(), 0])

class FlakySocket:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def settimeout(self, timeout):
        pass

    def connect_ex(self, address):
        outcome = next(outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

socket.socket = FlakySocket
"""
    completed = subprocess.run(
        [sys.executable, "-c", f"{flaky_socket_setup}\n{kubernetes_runner._WAIT_FOR_GAME_SERVICE_SCRIPT}"],
        env={
            **os.environ,
            "COWORLD_GAME_HOST": "game-service",
            "COWORLD_GAME_PORT": "8080",
            "COWORLD_GAME_WAIT_TIMEOUT_SECONDS": "2",
        },
        check=False,
        timeout=3,
    )

    assert completed.returncode == 0


def test_create_player_pod_applies_cpu_limit_and_pins_thread_pools(monkeypatch):
    created: dict[str, Any] = {}
    core_v1 = SimpleNamespace(create_namespaced_pod=lambda *, namespace, body: created.update({"body": body}))
    # An author who pins their own thread count keeps it; the limit only fills the unset knobs.
    player = PlayerLaunchSpec(image="paintbot:latest", run=(), env={"OMP_NUM_THREADS": "3"})

    kubernetes_runner._create_player_pod(
        core_v1, "jobs", "job-player-0", 0, "slot-token", player, {}, "job-id", "game-service", "250m", "256Mi", "8", []
    )

    pod: Any = created["body"]
    container: Any = pod.spec.containers[0]
    assert container.resources.requests == {"cpu": "250m", "memory": "256Mi"}
    assert container.resources.limits == {"cpu": "8"}
    env = {ev.name: ev.value for ev in container.env}
    assert env["MKL_NUM_THREADS"] == "8"
    assert env["OPENBLAS_NUM_THREADS"] == "8"
    assert env["NUMEXPR_NUM_THREADS"] == "8"
    # The author's explicit thread pin wins over the limit-derived default.
    assert env["OMP_NUM_THREADS"] == "3"


def test_create_player_pod_without_cpu_limit_omits_limit_and_thread_env(monkeypatch):
    created: dict[str, Any] = {}
    core_v1 = SimpleNamespace(create_namespaced_pod=lambda *, namespace, body: created.update({"body": body}))
    player = PlayerLaunchSpec(image="paintbot:latest", run=(), env={})

    kubernetes_runner._create_player_pod(
        core_v1, "jobs", "job-player-0", 0, "slot-token", player, {}, "job-id", "game-service", "250m", "256Mi", "", []
    )

    pod: Any = created["body"]
    container: Any = pod.spec.containers[0]
    assert container.resources.limits is None
    env = {ev.name: ev.value for ev in container.env}
    assert "OMP_NUM_THREADS" not in env
    assert "MKL_NUM_THREADS" not in env


def test_local_bedrock_player_uses_direct_access_without_sidecar_infrastructure(monkeypatch):
    created: dict[str, Any] = {}
    core_v1 = SimpleNamespace(create_namespaced_pod=lambda *, namespace, body: created.update({"body": body}))
    monkeypatch.setenv("COWORLD_LOCAL_DEV", "true")
    monkeypatch.setenv("COWORLD_BEDROCK_REGION", "us-west-2")
    monkeypatch.delenv("BEDROCK_SIDECAR_IMAGE", raising=False)
    monkeypatch.delenv("BEDROCK_SIDECAR_ROLE_ARN", raising=False)

    kubernetes_runner._create_player_pod(
        core_v1,
        "jobs",
        "job-player-0",
        0,
        "slot-token",
        PlayerLaunchSpec(image="paintbot:latest", run=(), env={}),
        {"USE_BEDROCK": "true"},
        "job-id",
        "game-service",
        "2",
        "2Gi",
        "",
        [],
    )

    pod: Any = created["body"]
    env = {env_var.name: env_var.value for env_var in pod.spec.containers[0].env}
    assert env["AWS_REGION"] == "us-west-2"
    assert env["AWS_DEFAULT_REGION"] == "us-west-2"
    assert "AWS_ENDPOINT_URL_BEDROCK_RUNTIME" not in env
    assert [container.name for container in pod.spec.init_containers] == ["wait-for-game-service"]
    assert pod.spec.service_account_name == "episode-runner"
    assert pod.spec.automount_service_account_token is None


def test_create_player_pod_with_bedrock_sidecar_inverts_bedrock_access(monkeypatch):
    created: dict[str, Any] = {}
    core_v1 = SimpleNamespace(create_namespaced_pod=lambda *, namespace, body: created.update({"body": body}))
    monkeypatch.setenv("COWORLD_BEDROCK_REGION", "us-west-2")
    monkeypatch.setenv("BEDROCK_SIDECAR_IMAGE", "ghcr.io/metta-ai/bedrock-sidecar:latest")
    monkeypatch.setenv("BEDROCK_SIDECAR_ROLE_ARN", "arn:aws:iam::583928386201:role/episode-runner-bedrock")
    monkeypatch.setenv("BEDROCK_SIDECAR_PORT", "19191")
    monkeypatch.setenv("BEDROCK_SIDECAR_UPSTREAM_ENDPOINT", "http://bedrock.local")
    monkeypatch.setenv("BEDROCK_SIDECAR_SPEND_LIMIT_USD", "1.5")
    monkeypatch.setenv("BEDROCK_SIDECAR_PRICING_JSON", '{"claude-sonnet-4-6":[3.0,15.0,0.3,3.75]}')
    player = PlayerLaunchSpec(
        image="ghcr.io/metta-ai/players/paintbot@sha256:player123",
        run=(),
        env={
            "PUBLIC_SETTING": "visible",
            "AWS_REGION": "from-player-env",
            "AWS_ACCESS_KEY_ID": "from-player-env",
        },
    )

    assert kubernetes_runner.resolve_image_attribution_key("ghcr.io/metta-ai/players/paintbot:latest") == (
        "ghcr.io/metta-ai/players/paintbot:latest"
    )

    kubernetes_runner._create_player_pod(
        core_v1,
        "jobs",
        "job-player-0",
        0,
        "slot-token",
        player,
        {
            "USE_BEDROCK": "true",
            "BEDROCK_MODEL": "us.amazon.nova-micro-v1:0",
            "AWS_DEFAULT_REGION": "from-policy-secret",
            "AWS_SECRET_ACCESS_KEY": "from-policy-secret",
            "AWS_SESSION_TOKEN": "from-policy-secret",
            "AWS_BEARER_TOKEN_BEDROCK": "from-policy-secret",
            "AWS_WEB_IDENTITY_TOKEN_FILE": "/tmp/token",
            "AWS_ROLE_ARN": "arn:aws:iam::123456789012:role/direct",
        },
        "job-id",
        "game-service",
        "2",
        "2Gi",
        "",
        [],
    )

    pod: Any = created["body"]
    assert pod.metadata.annotations == {
        "karpenter.sh/do-not-disrupt": "true",
        "eks.amazonaws.com/skip-containers": "player,bedrock-sidecar",
    }
    assert pod.spec.service_account_name == "episode-runner"
    assert pod.spec.automount_service_account_token is False
    # The player app is the only regular container; the sidecar is a native sidecar
    # (initContainer with restartPolicy=Always) so the restartPolicy=Never pod can still finish.
    assert [container.name for container in pod.spec.containers] == ["player"]
    assert [c.name for c in pod.spec.init_containers] == [
        "wait-for-game-service",
        BEDROCK_SIDECAR_CONTAINER_NAME,
    ]
    player_container: Any = pod.spec.containers[0]
    sidecar: Any = pod.spec.init_containers[1]
    assert sidecar.restart_policy == "Always"

    env = {env_var.name: env_var.value for env_var in player_container.env}
    assert env["PUBLIC_SETTING"] == "visible"
    assert env["BEDROCK_MODEL"] == "us.amazon.nova-micro-v1:0"
    # The reserved sidecar env wins over the policy's own values: the user set AWS_REGION /
    # AWS_ACCESS_KEY_ID in their env, but they're overridden by the placeholder creds and the
    # localhost endpoint — a policy cannot bypass or break the sidecar.
    assert env["AWS_ENDPOINT_URL_BEDROCK_RUNTIME"] == "http://127.0.0.1:19191"
    assert env["AWS_ACCESS_KEY_ID"] == "bedrock-sidecar"
    assert env["AWS_SECRET_ACCESS_KEY"] == "bedrock-sidecar"
    # Bearer-token (Bedrock API key) auth: the policy's own token is overridden by the placeholder.
    assert env["AWS_BEARER_TOKEN_BEDROCK"] == "bedrock-sidecar"
    assert env["AWS_REGION"] == "us-west-2"
    assert env["AWS_DEFAULT_REGION"] == "us-west-2"
    # The public enablement flag remains readable for player SDKs, while real-identity keys
    # the policy supplied are stripped from the app entirely.
    assert env["USE_BEDROCK"] == "true"
    assert "AWS_SESSION_TOKEN" not in env
    assert "AWS_WEB_IDENTITY_TOKEN_FILE" not in env
    assert "AWS_ROLE_ARN" not in env
    assert env["COWORLD_PLAYER_WS_URL"] == "ws://game-service:8080/player?slot=0&token=slot-token"
    assert env["COGAMES_ENGINE_WS_URL"] == "ws://game-service:8080/player?slot=0&token=slot-token"
    assert not player_container.volume_mounts

    volumes: dict[str, Any] = {volume.name: volume for volume in pod.spec.volumes}
    assert list(volumes) == [BEDROCK_SIDECAR_TOKEN_VOLUME_NAME]
    assert [mount.name for mount in sidecar.volume_mounts] == [BEDROCK_SIDECAR_TOKEN_VOLUME_NAME]
    sidecar_env = {env_var.name: env_var.value for env_var in sidecar.env}
    assert sidecar_env["BEDROCK_SIDECAR_LISTEN_PORT"] == "19191"
    assert sidecar_env["BEDROCK_SIDECAR_REGION"] == "us-west-2"
    assert sidecar_env["BEDROCK_SIDECAR_UPSTREAM_ENDPOINT"] == "http://bedrock.local"
    assert json.loads(sidecar_env["BEDROCK_SIDECAR_REQUEST_METADATA"]) == {
        "metadata_origin": "bedrock_sidecar",
        "episode_request_id": "11111111-1111-1111-1111-111111111111",
        "image_digest": "sha256:player123",
        "job_request_id": "22222222-2222-2222-2222-222222222222",
        "role": "player",
        "schema_version": "1",
        "slot": "0",
        "source": "coworld_episode",
    }
    # The dispatcher-forwarded league spend limit and server pricing snapshot reach the sidecar.
    assert sidecar_env["BEDROCK_SIDECAR_SPEND_LIMIT_USD"] == "1.5"
    assert sidecar_env["BEDROCK_SIDECAR_PRICING_JSON"] == '{"claude-sonnet-4-6":[3.0,15.0,0.3,3.75]}'
    # Self-provisioned IRSA on the sidecar (not webhook-dependent).
    assert sidecar_env["AWS_ROLE_ARN"] == "arn:aws:iam::583928386201:role/episode-runner-bedrock"
    assert sidecar_env["AWS_WEB_IDENTITY_TOKEN_FILE"] == BEDROCK_SIDECAR_TOKEN_FILE

    token_projection = volumes[BEDROCK_SIDECAR_TOKEN_VOLUME_NAME].projected.sources[0].service_account_token
    assert token_projection.audience == "sts.amazonaws.com"
    assert token_projection.path == "token"


def test_create_player_pod_sidecar_forwards_s3_sink_env(monkeypatch):
    """The player sidecar inherits the dispatcher's completion, relay, and body stores."""
    created: dict[str, Any] = {}
    core_v1 = SimpleNamespace(create_namespaced_pod=lambda *, namespace, body: created.update({"body": body}))
    monkeypatch.setenv("COWORLD_BEDROCK_REGION", "us-west-2")
    monkeypatch.setenv("BEDROCK_SIDECAR_IMAGE", "ghcr.io/metta-ai/bedrock-sidecar:latest")
    monkeypatch.setenv("BEDROCK_SIDECAR_ROLE_ARN", "arn:aws:iam::583928386201:role/episode-runner-bedrock")
    monkeypatch.setenv("BEDROCK_SIDECAR_PORT", "19191")
    monkeypatch.delenv("BEDROCK_SIDECAR_UPSTREAM_ENDPOINT", raising=False)
    monkeypatch.setenv("BEDROCK_SIDECAR_COMPLETIONS_BUCKET", "softmax-bedrock-logs-583928386201")
    monkeypatch.setenv("BEDROCK_SIDECAR_LLM_RELAY_S3_BUCKET", "softmax-llm-records")
    monkeypatch.setenv("BEDROCK_SIDECAR_LLM_RELAY_S3_PREFIX", "llm-relay/custom")
    monkeypatch.setenv("BEDROCK_SIDECAR_LLM_DEBUG_BODY_S3_BUCKET", "softmax-llm-records")
    monkeypatch.setenv("BEDROCK_SIDECAR_OPENROUTER_CAPTURE_PAYLOADS", "false")
    monkeypatch.setenv("BEDROCK_SIDECAR_COMPLETIONS_PREFIX", "sidecar-completions")
    monkeypatch.setenv("BEDROCK_SIDECAR_FLUSH_RECORDS", "200")
    monkeypatch.setenv("BEDROCK_SIDECAR_FLUSH_SECONDS", "30.0")
    monkeypatch.setenv("BEDROCK_SIDECAR_PROMPT_PREFIX_SAMPLE_RATE", "0.5")

    kubernetes_runner._create_player_pod(
        core_v1,
        "jobs",
        "job-player-0",
        0,
        "slot-token",
        PlayerLaunchSpec(image="ghcr.io/metta-ai/players/paintbot@sha256:player123", run=(), env={}),
        {"USE_BEDROCK": "true"},
        "job-id",
        "game-service",
        "2",
        "2Gi",
        "",
        [],
    )

    sidecar: Any = next(
        container
        for container in created["body"].spec.init_containers
        if container.name == BEDROCK_SIDECAR_CONTAINER_NAME
    )
    sidecar_values = {env_var.name: env_var.value for env_var in sidecar.env}
    assert sidecar_values["BEDROCK_SIDECAR_COMPLETIONS_BUCKET"] == "softmax-bedrock-logs-583928386201"
    assert sidecar_values["BEDROCK_SIDECAR_COMPLETIONS_PREFIX"] == "sidecar-completions"
    assert sidecar_values["BEDROCK_SIDECAR_FLUSH_RECORDS"] == "200"
    assert sidecar_values["BEDROCK_SIDECAR_FLUSH_SECONDS"] == "30.0"
    assert sidecar_values["BEDROCK_SIDECAR_LLM_RELAY_S3_BUCKET"] == "softmax-llm-records"
    assert sidecar_values["BEDROCK_SIDECAR_LLM_RELAY_S3_PREFIX"] == "llm-relay/custom"
    assert sidecar_values["BEDROCK_SIDECAR_LLM_DEBUG_BODY_S3_BUCKET"] == "softmax-llm-records"
    assert sidecar_values["BEDROCK_SIDECAR_OPENROUTER_CAPTURE_PAYLOADS"] == "false"
    assert sidecar_values["BEDROCK_SIDECAR_PROMPT_PREFIX_SAMPLE_RATE"] == "0.5"
    assert sidecar_values["BEDROCK_SIDECAR_PROMPT_PREFIX_ENABLED_PATH"] == BEDROCK_PROMPT_PREFIX_ENABLED_PATH
    pod_name_env = next(env_var for env_var in sidecar.env if env_var.name == "POD_NAME")
    assert pod_name_env.value_from.field_ref.field_path == "metadata.name"
    control_projection = created["body"].spec.volumes[0].projected.sources[1].config_map
    assert control_projection.name == BEDROCK_PROMPT_PREFIX_CONTROL_CONFIG_MAP_NAME


def test_create_player_pod_forwards_artifact_upload_url_for_its_slot(monkeypatch):
    created: dict[str, Any] = {}
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
        "",
        [],
    )

    env = {env_var.name: env_var.value for env_var in created["body"].spec.containers[0].env}
    assert env["COWORLD_PLAYER_ARTIFACT_UPLOAD_URL"] == "https://s3.example/put/policy_artifact_1.zip"


def test_create_player_pod_tags_bedrock_request_metadata_with_slot(monkeypatch):
    created: dict[str, Any] = {}
    core_v1 = SimpleNamespace(create_namespaced_pod=lambda *, namespace, body: created.update({"body": body}))
    monkeypatch.setenv(
        "BEDROCK_REQUEST_METADATA",
        '{"episode_request_id":"11111111-1111-1111-1111-111111111111","image_digest":"sha256:game",'
        '"job_request_id":"22222222-2222-2222-2222-222222222222","metadata_origin":"dispatcher",'
        '"role":"game","schema_version":"1","slot":"game","source":"coworld_episode"}',
    )
    player = PlayerLaunchSpec(image="paintbot:latest", run=(), env={})

    kubernetes_runner._create_player_pod(
        core_v1, "jobs", "job-player-1", 1, "slot-token", player, {}, "job-id", "game-service", "2", "2Gi", "", []
    )

    env = {env_var.name: env_var.value for env_var in created["body"].spec.containers[0].env}
    assert json.loads(env["BEDROCK_REQUEST_METADATA"]) == {
        "metadata_origin": "coworld_runner",
        "episode_request_id": "11111111-1111-1111-1111-111111111111",
        "image_digest": "paintbot:latest",
        "job_request_id": "22222222-2222-2222-2222-222222222222",
        "role": "player",
        "schema_version": "1",
        "slot": "1",
        "source": "coworld_episode",
    }


def test_create_player_pod_requires_dispatcher_bedrock_metadata(monkeypatch):
    created: dict[str, Any] = {}
    core_v1 = SimpleNamespace(create_namespaced_pod=lambda *, namespace, body: created.update({"body": body}))
    monkeypatch.delenv("BEDROCK_REQUEST_METADATA", raising=False)
    player = PlayerLaunchSpec(image="paintbot:latest", run=(), env={})

    with pytest.raises(KeyError, match="BEDROCK_REQUEST_METADATA"):
        kubernetes_runner._create_player_pod(
            core_v1,
            "jobs",
            "job-player-0",
            0,
            "slot-token",
            player,
            {},
            "job-id",
            "game-service",
            "2",
            "2Gi",
            "",
            [],
        )


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


def test_write_error_info_marks_player_pod_failure_as_player_error(monkeypatch, tmp_path):
    error_dest = tmp_path / "error_info.json"
    monkeypatch.setenv("ERROR_INFO_URI", error_dest.as_uri())

    kubernetes_runner._write_error_info(kubernetes_runner.PlayerPodFailure(3, "player pod failed"))

    error_info = json.loads(error_dest.read_text(encoding="utf-8"))
    assert error_info["error_type"] == "player_error"
    assert error_info["failed_policy_index"] == 3
    assert error_info["message"] == "player pod failed"


def test_write_error_info_uses_typed_episode_error(monkeypatch, tmp_path):
    error_dest = tmp_path / "error_info.json"
    monkeypatch.setenv("ERROR_INFO_URI", error_dest.as_uri())

    kubernetes_runner._write_error_info(
        runner_io.RunnerEpisodeError("Timed out waiting for game container", error_type="episode_timeout")
    )

    error_info = json.loads(error_dest.read_text(encoding="utf-8"))
    assert error_info["error_type"] == "episode_timeout"
    assert error_info["failed_policy_index"] is None
    assert "Timed out waiting for game container" in error_info["message"]


def test_create_player_pod_keeps_default_service_account_without_bedrock():
    created: dict[str, Any] = {}
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
        "",
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


def _docker_publish_values(command: list[str]) -> list[str]:
    return [value for index, value in enumerate(command) if index > 0 and command[index - 1] == "-p"]


def _env_value(command: list[str], key: str) -> str | None:
    prefix = f"{key}="
    for index, value in enumerate(command):
        if index > 0 and command[index - 1] == "-e" and value.startswith(prefix):
            return value.removeprefix(prefix)
    return None


def _upload_env(monkeypatch, **overrides: str | None) -> list[tuple[str, bytes, str]]:
    """Arrange `_upload_outputs` with only the URIs a case cares about."""
    uploads: list[tuple[str, bytes, str]] = []
    monkeypatch.setattr(
        kubernetes_runner,
        "upload_data",
        lambda uri, data, *, content_type: uploads.append((uri, data, content_type)),
    )
    for name in ("RESULTS_URI", "REPLAY_URI", "EVENTS_URI", "DEBUG_URI", "POLICY_LOG_URLS"):
        monkeypatch.delenv(name, raising=False)
    for name, value in overrides.items():
        if value is not None:
            monkeypatch.setenv(name, value)
    return uploads


def test_upload_outputs_uploads_the_event_stream_when_the_game_wrote_one(tmp_path, monkeypatch):
    artifacts = EpisodeArtifacts.create(tmp_path)
    payload = b'{"tick":364,"kind":"shot","x":478.0,"y":411.0}\n'
    artifacts.events_path.write_bytes(payload)
    uploads = _upload_env(monkeypatch, EVENTS_URI="file:///tmp/events-out.json")

    _upload_outputs(artifacts)

    assert uploads == [("file:///tmp/events-out.json", payload, "application/json")]


def test_upload_outputs_skips_the_event_stream_when_the_game_wrote_none(tmp_path, monkeypatch):
    """Absence is an ORDINARY outcome, not a failure.

    Most coworlds emit no event stream at all, and one that does can still play
    an episode that produces no events. Treating a missing file the way results
    and replay are treated would raise FileNotFoundError and fail the upload
    step — turning "this game has no events" into "this episode broke".
    """
    artifacts = EpisodeArtifacts.create(tmp_path)
    assert not artifacts.events_path.exists()
    uploads = _upload_env(monkeypatch, EVENTS_URI="file:///tmp/events-out.json")

    _upload_outputs(artifacts)

    assert uploads == []
