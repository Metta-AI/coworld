import hashlib
import json
import logging
import os
import signal
import socket
import socketserver
import subprocess
import sys
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import httpx
import jsonschema
import pytest
from kubernetes.client import Configuration
from kubernetes.client.rest import ApiException

from coworld.manifest import validate_upload_manifest
from coworld.runner import bootstrap, init_config, kubernetes_runner
from coworld.runner import io as runner_io
from coworld.runner import runner as runner_module
from coworld.runner.kubernetes_runner import (
    _upload_outputs,
)
from coworld.runner.llm_sidecar_wiring import (
    EGRESS_RELAY_CA_FILE,
    EGRESS_RELAY_CLIENT_CERT_FILE,
    EGRESS_RELAY_CLIENT_KEY_FILE,
    LLM_SIDECAR_CONTAINER_NAME,
    LLM_SIDECAR_TOKEN_FILE,
    LLM_SIDECAR_TOKEN_VOLUME_NAME,
)
from coworld.runner.phase_timings import ProcessTimings, TimingClock
from coworld.runner.runner import EpisodeArtifacts, PlayerLaunchSpec
from coworld.types import (
    CoworldEpisodeJobSpec,
    CoworldPlayerFileSpec,
    CoworldRunnableResources,
    CoworldRunnableSpec,
)


@pytest.fixture(autouse=True)
def _player_service_wait_env(monkeypatch):
    monkeypatch.delenv("COWORLD_PLAYER_IMAGE_PULL_POLICY", raising=False)
    monkeypatch.setenv("COWORLD_COORDINATOR_IMAGE", "coworld-coordinator:latest")
    monkeypatch.setenv("COWORLD_OPENROUTER_KEY_SECRET_NAME", "episode-llm-key-test")
    monkeypatch.setenv("COWORLD_TIMEOUT_SECONDS", "60")
    monkeypatch.setenv("COWORLD_CHILD_POD_LIFETIME_SECONDS", "120")
    monkeypatch.setenv(
        "LLM_REQUEST_METADATA",
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

    monkeypatch.setattr(kubernetes_runner.config, "load_incluster_config", lambda: None)
    monkeypatch.setattr(kubernetes_runner.client.Configuration, "get_default_copy", lambda: loaded)
    monkeypatch.setattr(kubernetes_runner.client.Configuration, "set_default", lambda _configuration: None)

    kubernetes_runner._load_incluster_config(egress_enforcement_enabled=False)

    # Retries set for 429 backoff...
    retries = loaded.retries
    assert retries is not None
    assert 429 in retries.status_forcelist
    assert retries.respect_retry_after_header is True
    # ...but the auth fields the refresh hook manages are untouched.
    assert loaded.api_key == {"BearerToken": "sa-token"}
    assert loaded.api_key_prefix == {"BearerToken": "Bearer"}


def test_enforced_incluster_config_keeps_relay_hostname_after_token_refresh(monkeypatch):
    loaded = Configuration()
    loaded.host = "https://10.96.0.1"
    loaded.api_key = {"BearerToken": "old-token"}

    def sdk_refresh(configuration: Configuration) -> None:
        configuration.host = "https://10.96.0.1"
        configuration.api_key["BearerToken"] = "new-token"
        cast(Any, configuration).refresh_api_key_hook = sdk_refresh

    cast(Any, loaded).refresh_api_key_hook = sdk_refresh
    monkeypatch.setenv("COWORLD_EGRESS_RELAY_URL", "https://egress-relay-mtls.jobs.svc.cluster.local:3128")
    monkeypatch.setenv("COWORLD_EGRESS_RELAY_CA_FILE", "/tls/ca.crt")
    monkeypatch.setenv("COWORLD_EGRESS_RELAY_CLIENT_CERT_FILE", "/tls/client.crt")
    monkeypatch.setenv("COWORLD_EGRESS_RELAY_CLIENT_KEY_FILE", "/tls/client.key")
    monkeypatch.setattr(kubernetes_runner, "egress_relay_ssl_context", lambda **_kwargs: object())
    monkeypatch.setattr(kubernetes_runner.config, "load_incluster_config", lambda: None)
    monkeypatch.setattr(kubernetes_runner.client.Configuration, "get_default_copy", lambda: loaded)
    monkeypatch.setattr(kubernetes_runner.client.Configuration, "set_default", lambda _configuration: None)

    api_client = kubernetes_runner._load_incluster_config(egress_enforcement_enabled=True)
    assert loaded.host == "https://kubernetes.default.svc"

    for _ in range(2):
        assert loaded.refresh_api_key_hook is not None
        loaded.refresh_api_key_hook(loaded)
        assert loaded.host == "https://kubernetes.default.svc"

    assert loaded.api_key == {"BearerToken": "new-token"}
    api_client.close()


def _container_status(
    name: str,
    *,
    running: bool = False,
    waiting: bool = False,
    exit_code: int | None = None,
    last_exit_code: int | None = None,
    reason: str | None = None,
    message: str | None = None,
    finished_at: str | None = None,
):
    return SimpleNamespace(
        name=name,
        state=SimpleNamespace(
            running=object() if running else None,
            terminated=SimpleNamespace(
                exit_code=exit_code,
                reason=reason,
                message=message,
                finished_at=finished_at,
            )
            if exit_code is not None
            else None,
            waiting=SimpleNamespace(reason=reason, message=message) if waiting else None,
        ),
        last_state=SimpleNamespace(
            terminated=SimpleNamespace(exit_code=last_exit_code, reason=reason, message=message, finished_at=None)
            if last_exit_code is not None
            else None,
        ),
    )


def _runtime_job(player_runtime: str = "platform-hosted", players: list[object] | None = None) -> CoworldEpisodeJobSpec:
    return cast(
        CoworldEpisodeJobSpec,
        SimpleNamespace(
            manifest=SimpleNamespace(game=SimpleNamespace(player_runtime=player_runtime, task_environments={})),
            players=players or [],
            episode_tags={},
            results_schema={},
            game_config={},
        ),
    )


def _game_hosted_job(contents: list[bytes]) -> CoworldEpisodeJobSpec:
    manifest_path = Path(__file__).parent / "manifest_versions/v1/game_hosted_players_manifest.json"
    return CoworldEpisodeJobSpec(
        manifest=validate_upload_manifest(json.loads(manifest_path.read_text(encoding="utf-8"))).runtime_manifest,
        game_config={},
        players=[
            CoworldPlayerFileSpec(
                type="player-file",
                content_hash=hashlib.sha256(content).hexdigest(),
                size_bytes=len(content),
            )
            for content in contents
        ],
    )


def _configure_init_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    job: CoworldEpisodeJobSpec,
    player_file_uris: dict[str, str],
) -> Path:
    private_dir = tmp_path.with_name(tmp_path.name + "-private")
    private_dir.mkdir()
    monkeypatch.setattr(init_config, "COORDINATOR_SPEC_PATH", private_dir / "worker_spec.json")
    token_path = private_dir / "player_artifact_tokens.json"
    monkeypatch.setattr(init_config, "PLAYER_ARTIFACT_TOKENS_PATH", token_path)
    monkeypatch.setattr(kubernetes_runner, "PLAYER_ARTIFACT_TOKENS_PATH", token_path)
    job_spec_path = private_dir / "source_spec.json"
    job_spec_path.write_text(job.model_dump_json(by_alias=True), encoding="utf-8")
    error_path = tmp_path / "error_info.json"
    monkeypatch.setattr(init_config, "WORKDIR", tmp_path)
    monkeypatch.setattr(init_config, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(kubernetes_runner, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setenv("JOB_SPEC_URI", job_spec_path.as_uri())
    monkeypatch.setenv("COGAME_CONFIG_URI", (tmp_path / "config.json").as_uri())
    monkeypatch.setenv("PLAYER_FILE_URLS", json.dumps(player_file_uris))
    monkeypatch.setenv("ERROR_INFO_URI", error_path.as_uri())
    return error_path


def test_stage_player_files_preserves_shipped_v1_game_consumer(tmp_path):
    contents = [b"harvestbench player"]
    job = _game_hosted_job(contents)
    player_files = [player for player in job.players if isinstance(player, CoworldPlayerFileSpec)]
    artifacts = EpisodeArtifacts.create(tmp_path)

    runner_module.stage_player_files(player_files, lambda slot: contents[slot], artifacts)

    # Frozen before #26252: shipped games reject unknown fields, independently of today's models.
    seat_properties = {
        "slot": {"type": "integer", "minimum": 0},
        "file_uri": {"type": "string", "minLength": 1},
        "content_hash": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
        "size_bytes": {"type": "integer", "minimum": 0},
        "log_uri": {"type": "string", "minLength": 1},
        "artifact_uri": {"type": "string", "minLength": 1},
    }
    jsonschema.validate(
        json.loads(artifacts.player_seats_path.read_text()),
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["schema", "seats", "player_status_uri"],
            "properties": {
                "schema": {"const": "coworld-player-seats/1"},
                "seats": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": list(seat_properties),
                        "properties": seat_properties,
                    },
                },
                "player_status_uri": {"type": "string", "minLength": 1},
            },
        },
    )


def test_stage_player_files_exposes_annotations_for_opted_in_v2_game(tmp_path):
    contents = [b"annotation-capable player"]
    job = _game_hosted_job(contents)
    player_files = [player for player in job.players if isinstance(player, CoworldPlayerFileSpec)]
    artifacts = EpisodeArtifacts.create(tmp_path)

    runner_module.stage_player_files(
        player_files, lambda slot: contents[slot], artifacts, player_seats_schema="coworld-player-seats/2"
    )

    seats = json.loads(artifacts.player_seats_path.read_text())
    assert seats["schema"] == "coworld-player-seats/2"
    assert seats["seats"][0]["annotations_uri"] == "file:///coworld/policy_annotations_0.jsonl"


@pytest.mark.parametrize("status,expected_type", [(403, "config_error"), (503, "artifact_transport_error")])
def test_init_config_redacts_presigned_spec_download_error(monkeypatch, tmp_path, status, expected_type):
    job = _game_hosted_job([b"player"])
    error_path = _configure_init_env(monkeypatch, tmp_path, job, {})
    signed_url = "https://example.test/spec?X-Amz-Signature=secret&X-Amz-Credential=credential"
    monkeypatch.setenv("JOB_SPEC_URI", signed_url)
    request = httpx.Request("GET", signed_url)
    response = httpx.Response(status, request=request)
    download_error = httpx.HTTPStatusError(f"download failed: {signed_url}", request=request, response=response)

    def fail_download(_uri: str) -> bytes:
        raise download_error

    monkeypatch.setattr(bootstrap, "read_data", fail_download)

    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        init_config.init_config_from_env()

    assert exc_info.value is download_error
    error_info = json.loads(error_path.read_text(encoding="utf-8"))
    assert error_info["error_type"] == expected_type
    assert error_info["message"] == f"HTTPStatusError (HTTP status {status})"
    assert "X-Amz-" not in error_path.read_text(encoding="utf-8")


@pytest.mark.parametrize("actual", [b"playeX", b"short"])
def test_init_config_maps_player_file_digest_or_size_mismatch_to_structured_error(monkeypatch, tmp_path, actual):
    source = tmp_path / "source"
    source.write_bytes(actual)
    job = _game_hosted_job([b"player"])
    error_path = _configure_init_env(monkeypatch, tmp_path, job, {"0": source.as_uri()})

    with pytest.raises(runner_io.RunnerEpisodeError, match="does not match") as exc_info:
        init_config.init_config_from_env()

    assert exc_info.value.error_type == "player_file_mismatch"
    assert json.loads(error_path.read_text(encoding="utf-8"))["error_type"] == "player_file_mismatch"


def test_upload_outputs_rejects_symlinked_results(tmp_path, monkeypatch, caplog):
    artifacts = EpisodeArtifacts.create(tmp_path / "work")
    secret = tmp_path / "service-account-token"
    secret.write_text("credential", encoding="utf-8")
    artifacts.results_path.symlink_to(secret)
    uploads = _upload_env(monkeypatch, RESULTS_URI="file:///tmp/results-out.json")

    with caplog.at_level(logging.WARNING), pytest.raises(runner_io.RunnerEpisodeError, match="results disappeared"):
        _upload_outputs(artifacts)

    assert uploads == []
    assert str(artifacts.results_path) in caplog.text


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


@pytest.mark.parametrize("creation_fails", [False, True])
def test_prepare_players_creates_all_slots_or_cleans_partial_launch(monkeypatch, tmp_path, creation_fails):
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"tokens": ["token-0", "token-1", "token-2"]}))
    monkeypatch.setattr(kubernetes_runner, "STATE_PATH", state_path)
    monkeypatch.setenv("JOB_NAMESPACE", "jobs")
    monkeypatch.setenv("JOB_ID", "job-id")
    monkeypatch.setenv("POD_NAME", "parent-pod")
    monkeypatch.setenv("POD_UID", "parent-uid")
    monkeypatch.setenv("COWORLD_SERVICE_NAME", "game-service")
    monkeypatch.delenv("COWORLD_EGRESS_ENFORCEMENT_ENABLED", raising=False)
    monkeypatch.setattr(kubernetes_runner, "_load_incluster_config", lambda **kwargs: None)
    monkeypatch.setattr(
        kubernetes_runner,
        "_policy_secrets_from_env",
        lambda: {0: {"COWORLD_LLM_ENABLED": "true", "COWORLD_LLM_MODEL": "self-hosted/test"}},
    )
    monkeypatch.setenv("COWORLD_SELF_HOSTED_DEPLOYMENTS", '{"self-hosted/test":"coworld-inference"}')
    ready = []

    def wait_ready(_api, namespace, models, deployments):
        assert namespace == "jobs"
        assert models == {"self-hosted/test"}
        assert deployments == {"self-hosted/test": "coworld-inference"}
        core.create_namespaced_service.assert_not_called()
        create.assert_not_called()
        ready.append(True)

    monkeypatch.setattr(kubernetes_runner, "wait_for_self_hosted_models", wait_ready)
    core = MagicMock()
    monkeypatch.setattr(kubernetes_runner.client, "CoreV1Api", lambda _: core)
    create = MagicMock(side_effect=[None, RuntimeError("pod creation failed")] if creation_fails else None)
    monkeypatch.setattr(kubernetes_runner, "_create_player_pod", create)
    job = _runtime_job(players=[CoworldRunnableSpec(type="player", image="player:test") for _ in range(3)])
    job.players[0].resources = CoworldRunnableResources.model_validate(
        {"requests": {"cpu": "16", "memory": "40Gi"}, "limits": {"cpu": "16"}}
    )
    job.players[1].resources = CoworldRunnableResources.model_validate({"requests": {"cpu": "1", "memory": "1Gi"}})
    monkeypatch.setenv("COWORLD_PLAYER_CPU_LIMIT", "2")
    timings = ProcessTimings(clock=TimingClock.capture())

    with pytest.raises(RuntimeError, match="pod creation failed") if creation_fails else nullcontext():
        kubernetes_runner._prepare_player_pods(job, timings)

    assert ready == [True]
    expected_slots = list(range(2 if creation_fails else 3))
    assert [call.args[9:12] for call in create.call_args_list] == [
        ("16", "40Gi", "16"),
        ("1", "1Gi", ""),
        ("2", "2Gi", "2"),
    ][: len(expected_slots)]
    assert [call.args[3] for call in create.call_args_list] == expected_slots
    assert [call.args[4] for call in create.call_args_list] == [f"token-{slot}" for slot in expected_slots]
    core.create_namespaced_service.assert_called_once()
    if creation_fails:
        # Include the failed request's name: the API may have accepted it before the client failed.
        assert [call.kwargs["name"] for call in core.delete_namespaced_pod.call_args_list] == [
            "game-service-player-0",
            "game-service-player-1",
        ]
        core.delete_namespaced_service.assert_called_once_with(name="game-service", namespace="jobs")
    else:
        core.delete_namespaced_pod.assert_not_called()
        core.delete_namespaced_service.assert_not_called()
        assert "player_launch" in timings.intervals


def test_player_artifact_upload_excludes_game_and_other_seat_tokens(monkeypatch, tmp_path):
    manifest_path = Path(__file__).parent / "manifest_versions/v1/minimal_manifest.json"
    job = CoworldEpisodeJobSpec(
        manifest=validate_upload_manifest(json.loads(manifest_path.read_text())).runtime_manifest,
        game_config={},
        players=[CoworldRunnableSpec(type="player", image="player:test") for _ in range(2)],
    )
    _configure_init_env(monkeypatch, tmp_path, job, {})
    init_config.init_config_from_env()
    upload_tokens = json.loads(init_config.PLAYER_ARTIFACT_TOKENS_PATH.read_text())
    game_tokens = json.loads(init_config.STATE_PATH.read_text())["tokens"]
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert all(token.encode() not in path.read_bytes() for token in upload_tokens)

    # The game can overwrite shared state without acquiring an upload capability.
    init_config.STATE_PATH.write_text(json.dumps({"tokens": ["game-chosen"] * 2}))
    output = tmp_path / "uploaded.zip"
    monkeypatch.setenv("PLAYER_ARTIFACT_UPLOAD_URLS", json.dumps({"0": output.as_uri()}))
    monkeypatch.setattr(kubernetes_runner, "PLAYER_ARTIFACT_PORT", 0)
    server = kubernetes_runner._start_player_artifact_upload_server()
    assert server is not None
    finished = threading.Event()
    release = server._release_connection

    def release_connection(source):
        release(source)
        finished.set()

    monkeypatch.setattr(server, "_release_connection", release_connection)
    monkeypatch.setattr(kubernetes_runner, "PLAYER_ARTIFACT_PORT", server.server_address[1])
    url = kubernetes_runner._player_artifact_upload_url(0, "127.0.0.1")
    assert url is not None
    try:
        for token in [*game_tokens, "game-chosen", upload_tokens[1]]:
            finished.clear()
            with pytest.raises(HTTPError) as error:
                urlopen(Request(url.rsplit("/", 1)[0] + "/" + token, data=b"forged", method="PUT"), timeout=2)
            assert error.value.code == 403
            error.value.close()
            assert finished.wait(2)
        assert not output.exists()
        for payload in (b"first upload", b"updated upload"):
            finished.clear()
            with urlopen(Request(url, data=payload, method="PUT"), timeout=2) as response:
                assert response.status == 201
            assert finished.wait(2)
            assert output.read_bytes() == payload
    finally:
        server.shutdown()
        server.server_close()


def test_player_artifact_upload_server_allows_one_connection_per_player(monkeypatch):
    player_count = 8
    uploads_started = threading.Barrier(player_count)

    def upload_file(_uri, _file, *, size, content_type):
        assert size == 8
        assert content_type == "application/zip"
        uploads_started.wait(timeout=5)

    monkeypatch.setattr(kubernetes_runner, "PLAYER_ARTIFACT_PORT", 0)
    monkeypatch.setattr(kubernetes_runner, "_PLAYER_ARTIFACT_MAX_CONNECTIONS_PER_SOURCE", player_count)
    monkeypatch.setattr(kubernetes_runner, "upload_file", upload_file)
    server = kubernetes_runner._PlayerArtifactUploadServer(
        {slot: f"https://s3.example/artifact-{slot}" for slot in range(player_count)},
        [f"secret-{slot}" for slot in range(player_count)],
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]

    def upload(slot: int) -> int:
        with urlopen(
            Request(
                f"http://127.0.0.1:{port}/player-artifact/{slot}/secret-{slot}",
                data=b"artifact",
                method="PUT",
                headers={"Content-Type": "application/zip"},
            ),
            timeout=10,
        ) as response:
            return response.status

    try:
        with ThreadPoolExecutor(max_workers=player_count) as pool:
            statuses = list(pool.map(upload, range(player_count)))
    finally:
        server.shutdown()
        server.server_close()
        thread.join()

    assert statuses == [201] * player_count


def test_player_artifact_upload_server_enforces_total_header_deadline(monkeypatch):
    monkeypatch.setattr(kubernetes_runner, "PLAYER_ARTIFACT_PORT", 0)
    monkeypatch.setattr(kubernetes_runner, "_PLAYER_ARTIFACT_HEADER_DEADLINE_SECONDS", 0.05)
    server = kubernetes_runner._PlayerArtifactUploadServer({0: "https://s3.example/artifact"}, ["secret"])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = socket.create_connection(("127.0.0.1", server.server_address[1]), timeout=1)
    try:
        connection.sendall(b"P")
        assert connection.recv(1) == b""
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join()

    assert server.active_connections == 0


def test_create_player_pod_enforcement_removes_dns_and_uses_secure_pool(monkeypatch):
    created: dict[str, Any] = {}
    core_v1 = SimpleNamespace(
        create_namespaced_pod=lambda *, namespace, body: created.update({"namespace": namespace, "body": body})
    )
    monkeypatch.setenv("COWORLD_EGRESS_ENFORCEMENT_ENABLED", "true")
    monkeypatch.setenv("COWORLD_EGRESS_RELAY_IP", "172.20.10.20")
    monkeypatch.setenv("COWORLD_EGRESS_RELAY_URL", "https://egress-relay-mtls.jobs.svc.cluster.local:3128")
    monkeypatch.setenv("COWORLD_WORKLOAD_TYPE", "coworld-egress-jobs")
    monkeypatch.setenv("LLM_SIDECAR_REGION", "us-east-1")

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
        game_pod_ip="172.20.20.30",
    )

    pod = created["body"]
    assert pod.metadata.labels["coworld-egress-enforced"] == "true"
    assert pod.spec.node_selector == {"workload-type": "coworld-egress-jobs"}
    assert pod.spec.tolerations[0].value == "coworld-egress-jobs"
    assert [(alias.ip, alias.hostnames) for alias in pod.spec.host_aliases] == [
        ("172.20.20.30", ["game-service"]),
        ("172.20.10.20", ["egress-relay-mtls.jobs.svc.cluster.local"]),
    ]


def test_player_service_gate_waits_for_worker_viewer():
    viewer_ready = threading.Event()
    worker_polled = threading.Event()

    class GateHandler(socketserver.BaseRequestHandler):
        def handle(self):
            request = self.request.recv(4096)
            if request.startswith(b"GET /players-ready "):
                worker_polled.set()
                status = b"200 OK" if viewer_ready.is_set() else b"503 Service Unavailable"
            else:
                assert request.startswith(b"GET /healthz ")
                status = b"200 OK"
            self.request.sendall(b"HTTP/1.1 " + status + b"\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")

    with socketserver.TCPServer(("127.0.0.1", 0), GateHandler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        process = subprocess.Popen(
            [sys.executable, "-c", kubernetes_runner._WAIT_FOR_GAME_SERVICE_SCRIPT],
            env={
                **os.environ,
                "COWORLD_GAME_HOST": "127.0.0.1",
                "COWORLD_GAME_PORT": str(server.server_address[1]),
                "COWORLD_WORKER_HEALTH_PORT": str(server.server_address[1]),
            },
        )
        try:
            deadline = time.monotonic() + 30
            while not worker_polled.wait(0.05):
                assert process.poll() is None, "player escaped on game health without waiting for the worker viewer"
                assert time.monotonic() < deadline, "player never checked worker readiness"
            assert process.poll() is None
            viewer_ready.set()
            assert process.wait(timeout=30) == 0
        finally:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=3)
            server.shutdown()
            thread.join(timeout=1)


@pytest.mark.parametrize("local_dev", [False, True])
def test_create_player_pod_with_native_sidecar_overrides_provider_credentials(monkeypatch, local_dev):
    monkeypatch.setenv("COWORLD_LOCAL_DEV", str(local_dev).lower())
    created: dict[str, Any] = {}
    core_v1 = SimpleNamespace(create_namespaced_pod=lambda *, namespace, body: created.update({"body": body}))
    monkeypatch.setenv("LLM_SIDECAR_REGION", "us-west-2")
    monkeypatch.setenv("LLM_SIDECAR_IMAGE", "ghcr.io/metta-ai/llm-sidecar:latest")
    monkeypatch.setenv("LLM_SIDECAR_ROLE_ARN", "arn:aws:iam::583928386201:role/episode-runner-llm-records")
    monkeypatch.setenv("LLM_SIDECAR_PORT", "19191")
    monkeypatch.setenv("LLM_SIDECAR_REQUEST_LIMIT_PER_MINUTE", "120")
    monkeypatch.setenv("LLM_SIDECAR_SPEND_LIMIT_USD", "1.5")
    monkeypatch.setenv("LLM_SIDECAR_EGRESS_RELAY_URL", "https://egress-relay-mtls.jobs.svc.cluster.local:3128")
    player = PlayerLaunchSpec(
        image="ghcr.io/metta-ai/players/paintbot@sha256:player123",
        run=(),
        env={
            "PUBLIC_SETTING": "visible",
            "AWS_REGION": "from-player-env",
            "AWS_ACCESS_KEY_ID": "from-player-env",
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
            "COWORLD_LLM_ENABLED": "true",
            "COWORLD_LLM_MODEL": "amazon/nova-micro-v1",
            "AWS_DEFAULT_REGION": "from-policy-secret",
            "AWS_SECRET_ACCESS_KEY": "from-policy-secret",
            "AWS_SESSION_TOKEN": "from-policy-secret",
            "ANTHROPIC_API_KEY": "from-policy-secret",
            "ANTHROPIC_AUTH_TOKEN": "from-policy-secret",
            "ANTHROPIC_BASE_URL": "https://direct.example",
            "OPENAI_API_KEY": "from-policy-secret",
            "OPENAI_BASE_URL": "https://direct.example/v1",
            "OPENROUTER_API_KEY": "from-policy-secret",
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
    assert set(pod.metadata.annotations["eks.amazonaws.com/skip-containers"].split(",")) == {
        "player",
        LLM_SIDECAR_CONTAINER_NAME,
    }
    assert pod.spec.service_account_name == "episode-runner"
    assert pod.spec.automount_service_account_token is False
    player_container: Any = pod.spec.containers[0]
    sidecar: Any = pod.spec.init_containers[1]
    assert sidecar.restart_policy == "Always"

    env = {env_var.name: env_var.value for env_var in player_container.env}
    assert env["COWORLD_LLM_MODEL"] == "amazon/nova-micro-v1"
    # Platform endpoints and placeholder credentials override saved provider access.
    assert env["COWORLD_LLM_ENDPOINT"] == "http://127.0.0.1:19191"
    assert env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:19191"
    assert env["OPENAI_BASE_URL"] == "http://127.0.0.1:19191/v1"
    assert env["ANTHROPIC_API_KEY"] == "sidecar"
    assert env["ANTHROPIC_AUTH_TOKEN"] == "sidecar"
    assert env["OPENAI_API_KEY"] == "sidecar"
    assert "OPENROUTER_API_KEY" not in env
    assert "AWS_ACCESS_KEY_ID" not in env
    assert "AWS_SECRET_ACCESS_KEY" not in env
    # The public enablement flag remains readable for player SDKs, while real-identity keys
    # the policy supplied are stripped from the app entirely.
    assert env["COWORLD_LLM_ENABLED"] == "true"
    assert "AWS_SESSION_TOKEN" not in env
    assert "AWS_WEB_IDENTITY_TOKEN_FILE" not in env
    assert "AWS_ROLE_ARN" not in env
    assert not any("EGRESS_RELAY" in name for name in env)
    assert env["COWORLD_PLAYER_WS_URL"] == "ws://game-service:8080/player?slot=0&token=slot-token"
    assert env["COGAMES_ENGINE_WS_URL"] == "ws://game-service:8080/player?slot=0&token=slot-token"
    assert not player_container.volume_mounts

    volumes: dict[str, Any] = {volume.name: volume for volume in pod.spec.volumes}
    sidecar_env = {env_var.name: env_var.value for env_var in sidecar.env}
    # The per-pod request ceiling has to survive the worker -> sidecar hop, or the deploy
    # knob is dead config and the only way to change it is a new sidecar image.
    assert sidecar_env["LLM_SIDECAR_REQUEST_LIMIT_PER_MINUTE"] == "120"
    assert json.loads(sidecar_env["LLM_SIDECAR_REQUEST_METADATA"]) == {
        "metadata_origin": "llm_sidecar",
        "episode_request_id": "11111111-1111-1111-1111-111111111111",
        "image_digest": "sha256:player123",
        "job_request_id": "22222222-2222-2222-2222-222222222222",
        "role": "player",
        "schema_version": "1",
        "slot": "0",
        "source": "coworld_episode",
    }
    # The dispatcher-forwarded league spend limit reaches the sidecar.
    assert sidecar_env["LLM_SIDECAR_SPEND_LIMIT_USD"] == "1.5"
    api_key_env = next(entry for entry in sidecar.env if entry.name == "LLM_SIDECAR_OPENROUTER_API_KEY")
    assert api_key_env.value is None
    assert api_key_env.value_from.secret_key_ref.name == "episode-llm-key-test"
    assert api_key_env.value_from.secret_key_ref.key == "OPENROUTER_API_KEY"
    assert sidecar_env["LLM_SIDECAR_EGRESS_RELAY_URL"] == "https://egress-relay-mtls.jobs.svc.cluster.local:3128"
    assert sidecar_env["LLM_SIDECAR_EGRESS_RELAY_CLIENT_CERT_FILE"] == EGRESS_RELAY_CLIENT_CERT_FILE
    assert sidecar_env["LLM_SIDECAR_EGRESS_RELAY_CLIENT_KEY_FILE"] == EGRESS_RELAY_CLIENT_KEY_FILE
    assert sidecar_env["LLM_SIDECAR_EGRESS_RELAY_CA_FILE"] == EGRESS_RELAY_CA_FILE
    # Self-provisioned IRSA on the sidecar (not webhook-dependent).
    assert sidecar_env["AWS_ROLE_ARN"] == "arn:aws:iam::583928386201:role/episode-runner-llm-records"
    assert sidecar_env["AWS_WEB_IDENTITY_TOKEN_FILE"] == LLM_SIDECAR_TOKEN_FILE

    token_projection = volumes[LLM_SIDECAR_TOKEN_VOLUME_NAME].projected.sources[0].service_account_token
    assert token_projection.audience == "sts.amazonaws.com"
    assert token_projection.path == "token"


def test_create_player_pod_routes_every_sidecar_without_exposing_openrouter_key(monkeypatch) -> None:
    created: list[Any] = []
    core_v1 = SimpleNamespace(create_namespaced_pod=lambda *, namespace, body: created.append(body))
    monkeypatch.setenv("LLM_SIDECAR_REGION", "us-west-2")
    monkeypatch.setenv("LLM_SIDECAR_IMAGE", "ghcr.io/metta-ai/llm-sidecar:latest")
    monkeypatch.setenv("LLM_SIDECAR_ROLE_ARN", "arn:aws:iam::583928386201:role/episode-runner-llm-records")
    monkeypatch.setenv("LLM_SIDECAR_PORT", "19191")
    monkeypatch.setenv("LLM_SIDECAR_REQUEST_LIMIT_PER_MINUTE", "120")
    monkeypatch.setenv("COWORLD_OPENROUTER_KEY_SECRET_NAME", "episode-llm-key-episode-123")
    monkeypatch.setenv("COWORLD_OPENROUTER_API_KEY", "literal-key-must-not-appear")
    monkeypatch.setenv("COWORLD_OPENROUTER_MODEL_ALLOWLIST", '["anthropic/claude-sonnet-4.6"]')

    monkeypatch.setenv("COWORLD_OPENROUTER_ALLOWLIST_VERSION", "episode-v1")
    player = PlayerLaunchSpec(image="ghcr.io/metta-ai/players/paintbot@sha256:player123", run=(), env={})

    for slot in (0, 1):
        kubernetes_runner._create_player_pod(
            core_v1,
            "jobs",
            f"job-player-{slot}",
            slot,
            "slot-token",
            player,
            {"COWORLD_LLM_ENABLED": "true"},
            "job-id",
            "game-service",
            "2",
            "2Gi",
            "",
            [],
        )

    assert len(created) == 2
    for pod in created:
        player_env = {entry.name: entry.value for entry in pod.spec.containers[0].env}
        sidecar = next(
            container for container in pod.spec.init_containers if container.name == LLM_SIDECAR_CONTAINER_NAME
        )
        sidecar_env = {entry.name: entry.value for entry in sidecar.env}
        assert "COWORLD_OPENROUTER_KEY_SECRET_NAME" not in player_env
        assert "LLM_SIDECAR_OPENROUTER_API_KEY" not in player_env
        api_key_env = next(entry for entry in sidecar.env if entry.name == "LLM_SIDECAR_OPENROUTER_API_KEY")
        assert api_key_env.value is None
        assert api_key_env.value_from.secret_key_ref.name == "episode-llm-key-episode-123"
        assert api_key_env.value_from.secret_key_ref.key == "OPENROUTER_API_KEY"
        assert sidecar_env["LLM_SIDECAR_OPENROUTER_MODEL_ALLOWLIST"] == '["anthropic/claude-sonnet-4.6"]'

        assert sidecar_env["LLM_SIDECAR_OPENROUTER_ALLOWLIST_VERSION"] == "episode-v1"
        for container in [*pod.spec.containers, *pod.spec.init_containers]:
            for env in container.env or []:
                assert env.value != "literal-key-must-not-appear"
                if env.name == "LLM_SIDECAR_OPENROUTER_API_KEY":
                    assert env.value is None


def test_game_hosted_player_artifact_skips_symlink(monkeypatch, tmp_path, caplog):
    artifacts = EpisodeArtifacts.create(tmp_path / "work")
    secret = tmp_path / "service-account-token"
    secret.write_text("credential", encoding="utf-8")
    artifacts.policy_artifact_path(0).symlink_to(secret)
    uploads = []
    monkeypatch.setenv("PLAYER_ARTIFACT_UPLOAD_URLS", '{"0":"https://example.test/artifact"}')
    monkeypatch.setattr(kubernetes_runner, "upload_file", lambda *_args, **_kwargs: uploads.append(True))

    with caplog.at_level(logging.WARNING):
        oversize_count = kubernetes_runner._upload_player_artifacts(artifacts)

    assert oversize_count == 0
    assert uploads == []
    assert str(artifacts.policy_artifact_path(0)) in caplog.text


def test_game_hosted_failure_uploads_debug_artifacts_but_not_results(monkeypatch, tmp_path):
    artifacts = EpisodeArtifacts.create(tmp_path / "work")
    error_dest = tmp_path / "error-info.json"
    log_dest = tmp_path / "policy-0.log"
    artifact_dest = tmp_path / "policy-0.zip"
    debug_dest = tmp_path / "debug.zip"
    results_dest = tmp_path / "results.json"
    replay_dest = tmp_path / "replay.bin"

    def run_episode(*_args, **_kwargs):
        artifacts.game_stdout_path.write_text("game crashed", encoding="utf-8")
        artifacts.policy_log_path(0).write_text("seat zero log", encoding="utf-8")
        artifacts.policy_artifact_path(0).write_bytes(b"artifact zip bytes")
        artifacts.results_path.write_text('{"partial":true}', encoding="utf-8")
        artifacts.replay_path.write_bytes(b"partial replay")
        raise runner_io.RunnerEpisodeError("game crashed", error_type="game_unhealthy")

    monkeypatch.setattr(kubernetes_runner, "WORKDIR", artifacts.workspace)
    monkeypatch.setattr(kubernetes_runner, "STATE_PATH", artifacts.workspace / "state.json")
    monkeypatch.setattr(kubernetes_runner, "_start_worker_health_server", lambda _port: None)
    monkeypatch.setattr(
        kubernetes_runner, "_read_job_spec", lambda _timings: (_runtime_job("game-hosted", [object()]), b"{}")
    )
    monkeypatch.setattr(kubernetes_runner.EpisodeArtifacts, "create", lambda _workdir, prefix: artifacts)
    monkeypatch.setattr(kubernetes_runner, "_run_kubernetes_episode", run_episode)
    monkeypatch.setenv("ERROR_INFO_URI", error_dest.as_uri())
    monkeypatch.setenv("POLICY_LOG_URLS", json.dumps({"0": log_dest.as_uri()}))
    monkeypatch.setenv("PLAYER_ARTIFACT_UPLOAD_URLS", json.dumps({"0": artifact_dest.as_uri()}))
    monkeypatch.setenv("DEBUG_URI", debug_dest.as_uri())
    monkeypatch.setenv("RESULTS_URI", results_dest.as_uri())
    monkeypatch.setenv("REPLAY_URI", replay_dest.as_uri())
    for name in ("EVENTS_URI", "PLAYER_STATUS_URI", "WORKER_TIMINGS_URI"):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(runner_io.RunnerEpisodeError, match="game crashed"):
        kubernetes_runner.run_from_env()

    assert json.loads(error_dest.read_text(encoding="utf-8"))["error_type"] == "game_unhealthy"
    assert log_dest.read_text(encoding="utf-8") == "seat zero log"
    assert artifact_dest.read_bytes() == b"artifact zip bytes"
    assert debug_dest.exists()
    assert not results_dest.exists()
    assert not replay_dest.exists()


def test_game_hosted_failure_preserves_original_error_with_garbage_status(monkeypatch, tmp_path):
    artifacts = EpisodeArtifacts.create(tmp_path / "work")
    error_dest = tmp_path / "error-info.json"

    def run_episode(*_args, **_kwargs):
        artifacts.player_status_path.write_bytes(b"\xff\xfe")
        raise runner_io.RunnerEpisodeError("original timeout", error_type="episode_timeout")

    monkeypatch.setattr(kubernetes_runner, "WORKDIR", artifacts.workspace)
    monkeypatch.setattr(kubernetes_runner, "STATE_PATH", artifacts.workspace / "state.json")
    monkeypatch.setattr(kubernetes_runner, "_start_worker_health_server", lambda _port: None)
    monkeypatch.setattr(kubernetes_runner, "_read_job_spec", lambda _timings: (_runtime_job("game-hosted"), b"{}"))
    monkeypatch.setattr(kubernetes_runner.EpisodeArtifacts, "create", lambda _workdir, prefix: artifacts)
    monkeypatch.setattr(kubernetes_runner, "_run_kubernetes_episode", run_episode)
    monkeypatch.setenv("ERROR_INFO_URI", error_dest.as_uri())
    monkeypatch.setenv("PLAYER_ARTIFACT_UPLOAD_URLS", "{}")
    for name in (
        "RESULTS_URI",
        "REPLAY_URI",
        "EVENTS_URI",
        "PLAYER_STATUS_URI",
        "DEBUG_URI",
        "POLICY_LOG_URLS",
        "WORKER_TIMINGS_URI",
    ):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(runner_io.RunnerEpisodeError, match="original timeout"):
        kubernetes_runner.run_from_env()

    assert json.loads(error_dest.read_text(encoding="utf-8"))["error_type"] == "episode_timeout"


def test_run_from_env_preserves_episode_error_when_error_info_upload_fails(monkeypatch, tmp_path, caplog):
    artifacts = EpisodeArtifacts.create(tmp_path)
    original_error = RuntimeError("episode failed")

    def fail_episode(*_args, **_kwargs):
        raise original_error

    def fail_upload(*_args, **_kwargs):
        raise OSError("error-info upload failed")

    monkeypatch.setattr(kubernetes_runner, "WORKDIR", tmp_path)
    monkeypatch.setattr(kubernetes_runner, "_start_worker_health_server", lambda _port: None)
    monkeypatch.setattr(kubernetes_runner, "_read_job_spec", lambda _timings: (_runtime_job(), b"{}"))
    monkeypatch.setattr(kubernetes_runner.EpisodeArtifacts, "create", lambda _workdir, prefix: artifacts)
    monkeypatch.setattr(kubernetes_runner, "_run_kubernetes_episode", fail_episode)
    monkeypatch.setattr(bootstrap, "upload_data", fail_upload)
    monkeypatch.setenv("ERROR_INFO_URI", "https://example.test/error-info")
    for name in ("DEBUG_URI", "POLICY_LOG_URLS", "PLAYER_STATUS_URI", "WORKER_TIMINGS_URI"):
        monkeypatch.delenv(name, raising=False)

    with caplog.at_level(logging.WARNING), pytest.raises(RuntimeError) as exc_info:
        kubernetes_runner.run_from_env()

    assert exc_info.value is original_error
    assert "Failed to upload error info after episode failure: OSError (HTTP status unavailable)" in caplog.text


@pytest.mark.parametrize("error_type", [httpx.ConnectError, OSError, ValueError, KeyError])
def test_worker_succeeds_when_only_timing_publication_fails(monkeypatch, caplog, error_type):
    monkeypatch.setattr(kubernetes_runner, "_start_worker_health_server", lambda port: None)
    monkeypatch.setattr(kubernetes_runner, "_read_job_spec", lambda timings: (_runtime_job(), b"{}"))
    monkeypatch.setattr(kubernetes_runner.EpisodeArtifacts, "create", lambda *args, **kwargs: object())
    monkeypatch.setattr(kubernetes_runner, "_run_kubernetes_episode", lambda *args, **kwargs: None)
    published = []
    monkeypatch.setattr(kubernetes_runner, "_upload_outputs", lambda artifacts: published.append("results and replay"))

    async def fail_timings(*args, **kwargs):
        raise error_type("Timing upload failed https://example.test/timings?secret=hidden")

    monkeypatch.setenv("WORKER_TIMINGS_URI", "https://example.test/timings?secret=hidden")
    monkeypatch.setattr(kubernetes_runner, "upload_data_with_deadline", fail_timings)
    kubernetes_runner.run_from_env()
    assert published == ["results and replay"]
    assert "timing_upload_failed" in caplog.text
    assert "secret=hidden" not in caplog.text


def _upload_env(monkeypatch, **overrides: str | None) -> list[tuple[str, bytes, str]]:
    """Arrange `_upload_outputs` with only the URIs a case cares about."""
    uploads: list[tuple[str, bytes, str]] = []
    monkeypatch.setattr(
        kubernetes_runner,
        "upload_data",
        lambda uri, data, *, content_type: uploads.append((uri, data, content_type)),
    )
    for name in (
        "RESULTS_URI",
        "REPLAY_URI",
        "EVENTS_URI",
        "TRAJECTORY_URI",
        "PLAYER_STATUS_URI",
        "DEBUG_URI",
        "POLICY_LOG_URLS",
    ):
        monkeypatch.delenv(name, raising=False)
    for name, value in overrides.items():
        if value is not None:
            monkeypatch.setenv(name, value)
    return uploads


def test_game_authored_file_read_does_not_block_on_a_fifo(tmp_path):
    fifo = tmp_path / "policy_agent_0.log"
    os.mkfifo(fifo)

    assert kubernetes_runner._read_game_authored_file(fifo, None) is None


def test_run_from_env_reports_a_bad_replay_as_a_runner_error_without_publishing_results(monkeypatch, tmp_path):
    job = _game_hosted_job([b"alpha player", b"beta player"])
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(job.model_dump_json(by_alias=True), encoding="utf-8")
    error_path = tmp_path / "error_info.json"
    results_out = tmp_path / "results-out.json"
    secret = tmp_path / "service-account-token"
    secret.write_text("credential", encoding="utf-8")

    def fake_episode(job_spec, artifacts, **_kwargs):
        artifacts.results_path.write_text("{}", encoding="utf-8")
        artifacts.replay_path.symlink_to(secret)

    monkeypatch.setattr(kubernetes_runner, "WORKDIR", tmp_path)
    monkeypatch.setattr(kubernetes_runner, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(kubernetes_runner, "_start_worker_health_server", lambda _port: None)
    monkeypatch.setattr(kubernetes_runner, "_run_kubernetes_episode", fake_episode)
    monkeypatch.setenv("JOB_SPEC_URI", spec_path.as_uri())
    monkeypatch.setenv("ERROR_INFO_URI", error_path.as_uri())
    monkeypatch.setenv("RESULTS_URI", results_out.as_uri())
    monkeypatch.setenv("REPLAY_URI", (tmp_path / "replay-out").as_uri())
    for name in (
        "DEBUG_URI",
        "POLICY_LOG_URLS",
        "PLAYER_STATUS_URI",
        "WORKER_TIMINGS_URI",
        "PLAYER_ARTIFACT_UPLOAD_URLS",
    ):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(runner_io.RunnerEpisodeError, match="not a regular file"):
        kubernetes_runner.run_from_env()

    assert json.loads(error_path.read_text(encoding="utf-8"))["error_type"] == "replay_missing"
    assert not results_out.exists()


@pytest.mark.parametrize("ancestor", [False, True])
def test_debug_archive_rejects_symlinked_directories(tmp_path, ancestor):
    private = tmp_path / "private"
    (private / "logs").mkdir(parents=True)
    (private / "logs" / "targets.json").write_text("private upload credentials")
    link = tmp_path / "work"
    link.symlink_to(private if ancestor else private / "logs", target_is_directory=True)
    logs_dir = link / "logs" if ancestor else link

    destination = tmp_path / "debug.zip"
    kubernetes_runner._upload_debug_archive(destination.as_uri(), logs_dir, {})
    with zipfile.ZipFile(destination) as archive:
        assert archive.namelist() == []


@pytest.mark.parametrize(
    ("statuses", "expected_error"),
    [
        ([_container_status("player", running=True)], "episode_inconclusive"),
        (None, "episode_inconclusive"),
    ],
)
def test_certification_noncompletion_does_not_blame_player(statuses, expected_error):
    core_v1 = _FakeGateCoreV1(reads={"job-player-0": [statuses]})
    with pytest.raises(runner_io.RunnerEpisodeError) as exc_info:
        kubernetes_runner._wait_for_players_to_complete(core_v1, "default", ["job-player-0"], timeout_seconds=0.0)
    assert exc_info.value.error_type == expected_error
    assert exc_info.value.failed_policy_index is None


def test_local_player_exit_timeout_is_inconclusive(tmp_path):
    class HangingPlayer:
        def wait(self, *, timeout):
            raise subprocess.TimeoutExpired("player", timeout)

    with pytest.raises(runner_io.RunnerEpisodeError) as excinfo:
        runner_module._wait_for_player_exit(
            cast(subprocess.Popen[str], HangingPlayer()), tmp_path / "stderr", failed_policy_index=2, timeout_seconds=30
        )
    assert excinfo.value.error_type == "episode_inconclusive"
    assert excinfo.value.failed_policy_index is None
    assert "slot 2" in str(excinfo.value)
    assert "30s" in str(excinfo.value)
    assert "valid results" in str(excinfo.value)


@pytest.mark.parametrize("exit_code", [1, 75])
def test_local_player_nonzero_exit_keeps_player_blame(tmp_path, exit_code):
    player = cast(subprocess.Popen[str], SimpleNamespace(wait=lambda **_: exit_code))
    with pytest.raises(runner_io.RunnerEpisodeError) as excinfo:
        runner_module._wait_for_player_exit(player, tmp_path / "stderr", failed_policy_index=2)
    assert excinfo.value.error_type == "player_error"
    assert excinfo.value.failed_policy_index == 2


@pytest.mark.parametrize(
    "note",
    [
        None,
        b'{"protocol":"append-v1","notes":{}}',
        json.dumps(
            {"protocol": "append-v1", "notes": {f"sha256:{index:064x}": "\x00" * 16384 for index in range(128)}}
        ).encode(),
    ],
    ids=["absent", "empty-notes", "large-notes"],
)
def test_private_memory_upload_precedes_results(tmp_path, monkeypatch, note):
    artifacts = EpisodeArtifacts.create(tmp_path)
    artifacts.results_path.write_text("{}")
    if note is not None:
        (artifacts.workspace / "memory-output.json").write_bytes(note)
    monkeypatch.setenv("SCRATCHPAD_OUTPUT_URI", "file:///private/memory.json")
    monkeypatch.setenv("RESULTS_URI", "file:///public/results.json")
    monkeypatch.delenv("REPLAY_URI", raising=False)
    uploads = []
    monkeypatch.setattr(kubernetes_runner, "upload_data", lambda uri, data, **kw: uploads.append((uri, data)))
    _upload_outputs(artifacts)
    assert uploads[0][0] == "file:///private/memory.json"
    assert json.loads(uploads[0][1]) == (
        json.loads(note) if note is not None else {"protocol": "append-v1", "notes": {}}
    )
    assert uploads[1][0] == "file:///public/results.json"


def test_worker_sigterm_enters_existing_failure_cleanup(monkeypatch):
    handlers = {}
    monkeypatch.setattr(kubernetes_runner.signal, "signal", lambda signum, handler: handlers.update({signum: handler}))
    monkeypatch.setattr(kubernetes_runner.sys, "argv", ["runner", "run-core-sidecars-v1"])
    monkeypatch.setattr(
        kubernetes_runner, "run_from_env", lambda **kwargs: handlers[signal.SIGTERM](signal.SIGTERM, None)
    )
    with pytest.raises(kubernetes_runner.RunnerEpisodeError, match="Worker received signal") as exc:
        kubernetes_runner.main()
    assert exc.value.error_type == "worker_error"


@pytest.mark.parametrize("source,slot", [("coworld_play", 0), ("coworld_replay", 0), ("coworld_persistent", 1)])
def test_player_pod_rejects_wrong_runtime_identity(monkeypatch, source, slot):
    metadata = dict(
        schema_version="1",
        source=source,
        metadata_origin="llm_sidecar",
        coworld_id="cow_test",
        role="player",
        slot="0",
        image_digest="sha256:test",
    )
    if source == "coworld_play":
        metadata["play_session_id"] = "play_test"
    if source == "coworld_persistent":
        metadata.update(
            runtime_id="22222222-2222-2222-2222-222222222222",
            runtime_generation="1",
            league_id="league_test",
            player_id="player_test",
            policy_version_id="33333333-3333-3333-3333-333333333333",
        )
    monkeypatch.setenv("LLM_REQUEST_METADATA", json.dumps(metadata))
    created = []
    core_v1 = SimpleNamespace(create_namespaced_pod=lambda **kwargs: created.append(kwargs))
    with pytest.raises(ValueError):
        kubernetes_runner._create_player_pod(
            core_v1,
            "jobs",
            "player",
            slot,
            "token",
            PlayerLaunchSpec(image="registry/player@sha256:test", run=(), env={}),
            {},
            "job",
            "game",
            "2",
            "2Gi",
            "",
            [],
        )
    assert created == []
