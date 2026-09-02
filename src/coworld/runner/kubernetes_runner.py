from __future__ import annotations

import argparse
import asyncio
import hmac
import http.server
import json
import logging
import os
import socket
import socketserver
import ssl
import sys
import tempfile
import threading
import time
import zipfile
from collections import Counter
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from typing import Any, Mapping, cast
from urllib.parse import urlsplit

import httpx
import urllib3
from kubernetes import client, config
from kubernetes.client.rest import ApiException
from kubernetes.utils import parse_quantity
from urllib3.exceptions import HTTPError
from urllib3.util import Retry

from coworld.runner.bedrock_enablement import BedrockEnablement, resolve_player_bedrock
from coworld.runner.bedrock_metadata import CoworldEpisodeBedrockMetadata, serialize_bedrock_request_metadata
from coworld.runner.bedrock_sidecar_wiring import (
    BEDROCK_SIDECAR_CONTAINER_NAME,
    COWORLD_EGRESS_ENFORCED_LABEL,
    RESERVED_SIDECAR_APP_ENV,
    bedrock_app_endpoint_env,
    bedrock_sidecar_token_volume,
    build_bedrock_sidecar,
    resolve_image_attribution_key,
)
from coworld.runner.io import (
    PlayerRuntimeStatus,
    PlayerRuntimeStatuses,
    RunnerEpisodeError,
    RunnerError,
    RunnerErrorType,
    read_data,
    upload_data,
    upload_file,
)
from coworld.runner.phase_timings import EpisodePhaseTimings
from coworld.runner.runner import (
    CERTIFICATION_EPISODE_SOURCE,
    DEFAULT_PLAYER_EXIT_TIMEOUT_SECONDS,
    DEFAULT_RUNTIME_STARTUP_TIMEOUT_SECONDS,
    LOBBY_RUNTIME_STARTUP_TIMEOUT_SECONDS,
    EpisodeArtifacts,
    PlayerLaunchSpec,
    _raise_if_game_declared_player_failure,
    _require_bad_player_rejected,
    _require_global_message,
    _require_http_ok,
    _validate_results_file,
    coworld_game_config,
    episode_player_tokens,
)
from coworld.runner.runner import (
    _player_query as _episode_player_query,
)
from coworld.types import CoworldEpisodeJobSpec, CoworldHumanPlayerSpec

logger = logging.getLogger(__name__)

WORKDIR = Path(os.environ.get("COWORLD_WORKDIR", "/coworld"))
STATE_PATH = WORKDIR / "state.json"
GAME_PORT = int(os.environ.get("COGAME_PORT", "8080"))
HEALTH_PORT = int(os.environ.get("COWORLD_WORKER_HEALTH_PORT", "9090"))
PLAYER_ARTIFACT_PORT = 9091
# Poll cadence for the two in-pod wait loops. Each tick issues a read_namespaced_pod against
# the API server; with many concurrent episodes the aggregate read rate contributes to API
# Priority & Fairness 429s (etcd throttle). Episodes run seconds-to-minutes, so a 1s cadence
# is latency-insensitive and cuts that steady read pressure.
_HEALTH_POLL_SECONDS = 1.0
_ARTIFACT_POLL_SECONDS = 1.0
_PLAYER_ARTIFACT_MAX_BYTES = 200 * 1024 * 1024
_PLAYER_ARTIFACT_HEADER_DEADLINE_SECONDS = 5.0
_PLAYER_ARTIFACT_BODY_DEADLINE_SECONDS = 60.0
_PLAYER_ARTIFACT_MAX_CONNECTIONS = 4
_PLAYER_ARTIFACT_MAX_CONNECTIONS_PER_SOURCE = 1
_PLAYER_ARTIFACT_MAX_ATTEMPTS = 3
_BEDROCK_SERVICE_ACCOUNT = "episode-runner"
_KUBERNETES_API_SERVICE_HOST = "kubernetes.default.svc"
_DIRECT_BEDROCK_APP_ENV = {
    "USE_BEDROCK",
    "AWS_REGION",
    "AWS_DEFAULT_REGION",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AWS_WEB_IDENTITY_TOKEN_FILE",
    "AWS_ROLE_ARN",
}
DEFAULT_PLAYER_CPU_REQUEST = "2"
DEFAULT_PLAYER_MEMORY_REQUEST = "2Gi"
# Keep the process-start gate inside the game's all-connected-or-timeout start window.
DEFAULT_PLAYER_CONNECT_TIMEOUT_SECONDS = 180.0
_PLAYER_WAITING_POLICY_FAILURE_REASONS = {
    "CrashLoopBackOff",
    "CreateContainerConfigError",
    "ErrImagePull",
    "ImagePullBackOff",
    "InvalidImageName",
}
# Standard math-library thread-pool knobs. PyTorch reads OMP_NUM_THREADS for its default
# intra-op thread count, so pinning these covers the common ML player stack.
_PLAYER_THREAD_POOL_ENV_VARS = (
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
)
_WAIT_FOR_GAME_SERVICE_SCRIPT = """
import contextlib
import os
import socket
import time

deadline = time.monotonic() + float(os.environ["COWORLD_GAME_WAIT_TIMEOUT_SECONDS"])
host = os.environ["COWORLD_GAME_HOST"]
port = int(os.environ["COWORLD_GAME_PORT"])
while time.monotonic() < deadline:
    with contextlib.suppress(socket.gaierror):
        with socket.socket() as connection:
            connection.settimeout(1)
            if connection.connect_ex((host, port)) == 0:
                raise SystemExit(0)
    time.sleep(0.5)
raise SystemExit(f"Timed out waiting for {host}:{port}")
""".strip()


def _player_thread_pool_env(cpu_limit: str) -> dict[str, str]:
    """Thread-pool env pinned to a player's CPU limit; empty limit -> no pinning.

    A CPU *limit* throttles compute but leaves os.cpu_count()/nproc reporting the node's core
    count, so NumPy/PyTorch/etc. would still size their pools to one-thread-per-node-core and
    thrash against the quota. Pinning these to floor(limit cores) makes the player behave like an
    N-core box regardless of which node size it lands on.
    """
    if not cpu_limit:
        return {}
    threads = max(1, int(parse_quantity(cpu_limit)))
    return {name: str(threads) for name in _PLAYER_THREAD_POOL_ENV_VARS}


class PlayerPodFailure(RunnerEpisodeError):
    def __init__(self, failed_policy_index: int, message: str):
        super().__init__(message, error_type="player_error", failed_policy_index=failed_policy_index)


class _HealthRequestHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        pass


def _start_worker_health_server(port: int) -> None:
    server = socketserver.TCPServer(("0.0.0.0", port), _HealthRequestHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()


class _PlayerArtifactUploadServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True

    def __init__(self, targets: dict[int, str], tokens: list[str]) -> None:
        super().__init__(("0.0.0.0", PLAYER_ARTIFACT_PORT), _PlayerArtifactUploadHandler)
        self.targets = targets
        self.tokens = tokens
        self.attempts: Counter[int] = Counter()
        self.completed_slots: set[int] = set()
        self.inflight_slots: set[int] = set()
        self.active_by_source: Counter[str] = Counter()
        self.active_connections = 0
        self.state_lock = threading.Lock()

    def process_request(self, request: Any, client_address: tuple[str, int]) -> None:
        source = client_address[0]
        with self.state_lock:
            if self.active_connections >= _PLAYER_ARTIFACT_MAX_CONNECTIONS:
                request.close()
                return
            if self.active_by_source[source] >= _PLAYER_ARTIFACT_MAX_CONNECTIONS_PER_SOURCE:
                request.close()
                return
            self.active_connections += 1
            self.active_by_source[source] += 1
        started = False
        try:
            super().process_request(request, client_address)
            started = True
        finally:
            if not started:
                self._release_connection(source)

    def process_request_thread(self, request: Any, client_address: tuple[str, int]) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._release_connection(client_address[0])

    def _release_connection(self, source: str) -> None:
        with self.state_lock:
            self.active_connections -= 1
            self.active_by_source[source] -= 1
            if self.active_by_source[source] == 0:
                del self.active_by_source[source]


class _PlayerArtifactUploadHandler(http.server.BaseHTTPRequestHandler):
    server: _PlayerArtifactUploadServer

    def _expire_deadline(self) -> None:
        try:
            self.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.connection.close()

    def setup(self) -> None:
        super().setup()
        self._deadline_timer = threading.Timer(_PLAYER_ARTIFACT_HEADER_DEADLINE_SECONDS, self._expire_deadline)
        self._deadline_timer.start()

    def parse_request(self) -> bool:
        parsed = super().parse_request()
        if parsed:
            self._deadline_timer.cancel()
            self._deadline_timer = threading.Timer(_PLAYER_ARTIFACT_BODY_DEADLINE_SECONDS, self._expire_deadline)
            self._deadline_timer.start()
        return parsed

    def finish(self) -> None:
        self._deadline_timer.cancel()
        super().finish()

    def do_PUT(self) -> None:
        parts = self.path.split("?")[0].split("/")
        if len(parts) != 4 or parts[1] != "player-artifact" or not parts[2].isdigit():
            self.send_error(404)
            return
        slot = int(parts[2])
        if slot not in self.server.targets or slot >= len(self.server.tokens):
            self.send_error(404)
            return
        if not hmac.compare_digest(parts[3], self.server.tokens[slot]):
            self.send_error(403)
            return
        content_length = self.headers.get("Content-Length", "")
        if not content_length.isdigit():
            self.send_error(411)
            return
        size = int(content_length)
        if size > _PLAYER_ARTIFACT_MAX_BYTES:
            self.send_error(413)
            return
        with self.server.state_lock:
            if slot in self.server.completed_slots:
                self.send_response(204)
                self.end_headers()
                return
            if slot in self.server.inflight_slots:
                self.send_error(409)
                return
            if self.server.attempts[slot] >= _PLAYER_ARTIFACT_MAX_ATTEMPTS:
                self.send_error(429)
                return
            self.server.attempts[slot] += 1
            self.server.inflight_slots.add(slot)
        try:
            with tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024) as artifact:
                remaining = size
                while remaining:
                    chunk = self.rfile.read(min(65536, remaining))
                    if not chunk:
                        self.send_error(400)
                        return
                    artifact.write(chunk)
                    remaining -= len(chunk)
                upload_file(
                    self.server.targets[slot],
                    artifact,
                    size=size,
                    content_type=self.headers.get("Content-Type", "application/zip"),
                )
            with self.server.state_lock:
                self.server.completed_slots.add(slot)
            self.send_response(201)
            self.end_headers()
        finally:
            with self.server.state_lock:
                self.server.inflight_slots.remove(slot)

    def log_message(self, _format: str, *args: object) -> None:
        # The path contains the player's upload capability. Never print it.
        pass


def _start_player_artifact_upload_server(tokens: list[str]) -> _PlayerArtifactUploadServer | None:
    raw_targets = os.environ.get("PLAYER_ARTIFACT_UPLOAD_URLS")
    if raw_targets is None or "COWORLD_EGRESS_RELAY_URL" not in os.environ:
        return None
    server = _PlayerArtifactUploadServer(
        targets={int(slot): url for slot, url in json.loads(raw_targets).items()},
        tokens=tokens,
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def init_config_from_env() -> None:
    job = _read_job_spec()
    tokens = episode_player_tokens(job)
    upload_data(
        os.environ["COGAME_CONFIG_URI"],
        json.dumps(coworld_game_config(job, tokens), indent=2),
        content_type="application/json",
    )
    STATE_PATH.write_text(json.dumps({"tokens": tokens}), encoding="utf-8")


def run_from_env() -> None:
    # Hold a TCP port open for the worker's entire lifetime so the game container can liveness-probe it.
    # When this process exits for any reason (timeout, crash, OOM) the kernel closes the socket, the
    # game's probe fails, and the kubelet tears the game container down instead of leaving a hard zombie.
    _start_worker_health_server(HEALTH_PORT)
    job = _read_job_spec()
    artifacts = EpisodeArtifacts.create(WORKDIR, prefix="coworld-job-")
    timings = EpisodePhaseTimings()
    timing_uploads: list[Future[None]] = []
    with ThreadPoolExecutor(max_workers=1) as timing_executor:

        def queue_timings_upload(current_timings: EpisodePhaseTimings) -> None:
            timing_uploads.append(timing_executor.submit(_upload_timings, current_timings.model_copy(deep=True)))

        try:
            _run_kubernetes_episode(
                job,
                artifacts,
                timeout_seconds=float(os.environ.get("COWORLD_TIMEOUT_SECONDS", "3600")),
                timings=timings,
                upload_timings=queue_timings_upload,
            )
        except Exception as exc:
            _write_error_info(exc)
            _upload_debug_logs(artifacts)
            raise
        upload_start = time.monotonic()
        _upload_outputs(artifacts)
        timings.artifact_upload_s = time.monotonic() - upload_start
        queue_timings_upload(timings)
        timing_uploads[-1].result()


def _read_job_spec() -> CoworldEpisodeJobSpec:
    return CoworldEpisodeJobSpec.model_validate_json(read_data(os.environ["JOB_SPEC_URI"]))


def _write_error_info(exc: Exception) -> None:
    error_info_uri = os.environ.get("ERROR_INFO_URI")
    if error_info_uri is None:
        return
    if isinstance(exc, RunnerEpisodeError):
        runner_error = RunnerError(
            error_type=cast(RunnerErrorType, exc.error_type),
            message=str(exc)[:2000],
            failed_policy_index=exc.failed_policy_index,
        )
    else:
        runner_error = RunnerError(error_type="crash", message=str(exc)[:2000])
    upload_data(error_info_uri, runner_error.model_dump_json(), content_type="application/json")


def _upload_debug_logs(artifacts: EpisodeArtifacts) -> None:
    _upload_player_status(artifacts)

    debug_uri = os.environ.get("DEBUG_URI")
    if debug_uri is not None and artifacts.logs_dir.exists() and any(artifacts.logs_dir.iterdir()):
        upload_data(debug_uri, _zip_logs(artifacts.logs_dir), content_type="application/zip")

    policy_log_urls = os.environ.get("POLICY_LOG_URLS")
    if policy_log_urls is not None:
        for slot, log_uri in json.loads(policy_log_urls).items():
            log_path = artifacts.policy_log_path(int(slot))
            if log_path.exists():
                upload_data(log_uri, log_path.read_bytes(), content_type="text/plain")


def _upload_timings(timings: EpisodePhaseTimings) -> None:
    timings_uri = os.environ.get("WORKER_TIMINGS_URI")
    if timings_uri is not None:
        upload_data(timings_uri, timings.model_dump_json(exclude_none=True), content_type="application/json")


def _upload_player_status(artifacts: EpisodeArtifacts) -> None:
    player_status_uri = os.environ.get("PLAYER_STATUS_URI")
    if player_status_uri is not None and artifacts.player_status_path.exists():
        upload_data(player_status_uri, artifacts.player_status_path.read_bytes(), content_type="application/json")


def _upload_outputs(artifacts: EpisodeArtifacts) -> None:
    _upload_player_status(artifacts)

    results_uri = os.environ.get("RESULTS_URI")
    if results_uri is not None:
        upload_data(results_uri, artifacts.results_path.read_bytes(), content_type="application/json")

    replay_uri = os.environ.get("REPLAY_URI")
    if replay_uri is not None:
        upload_data(
            replay_uri,
            artifacts.replay_path.read_bytes(),
            content_type="application/octet-stream",
        )

    # Existence-gated, unlike results/replay: most coworlds emit no event stream
    # at all, and a coworld that emits one may still finish an episode without a
    # single event. Both are ordinary outcomes, not a failed upload.
    events_uri = os.environ.get("EVENTS_URI")
    if events_uri is not None and artifacts.events_path.exists():
        upload_data(events_uri, artifacts.events_path.read_bytes(), content_type="application/json")

    debug_uri = os.environ.get("DEBUG_URI")
    if debug_uri is not None:
        upload_data(debug_uri, _zip_logs(artifacts.logs_dir), content_type="application/zip")

    policy_log_urls = os.environ.get("POLICY_LOG_URLS")
    if policy_log_urls is not None:
        for slot, log_uri in json.loads(policy_log_urls).items():
            log_path = artifacts.policy_log_path(int(slot))
            if log_path.exists():
                upload_data(log_uri, log_path.read_bytes(), content_type="text/plain")


def _zip_logs(logs_dir: Path) -> bytes:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in logs_dir.iterdir():
            if path.is_file():
                zf.write(path, path.name)
    return buf.getvalue()


def _run_kubernetes_episode(
    job: CoworldEpisodeJobSpec,
    artifacts: EpisodeArtifacts,
    *,
    timeout_seconds: float,
    timings: EpisodePhaseTimings,
    upload_timings: Callable[[EpisodePhaseTimings], None],
) -> None:
    worker_start = time.monotonic()
    egress_enforcement_enabled = os.environ.get("COWORLD_EGRESS_ENFORCEMENT_ENABLED") == "true"
    api_client = _load_incluster_config(egress_enforcement_enabled=egress_enforcement_enabled)
    core_v1 = client.CoreV1Api(api_client)
    namespace = os.environ["JOB_NAMESPACE"]
    service_name = os.environ["COWORLD_SERVICE_NAME"]
    job_id = os.environ["JOB_ID"]
    pod_name = os.environ["POD_NAME"]
    owner_references = _owner_references()
    tokens = json.loads(STATE_PATH.read_text(encoding="utf-8"))["tokens"]
    policy_players = [
        (slot, PlayerLaunchSpec.from_model(player))
        for slot, player in enumerate(job.players)
        if not isinstance(player, CoworldHumanPlayerSpec)
    ]
    is_lobby = len(policy_players) != len(job.players)
    startup_timeout_seconds = (
        LOBBY_RUNTIME_STARTUP_TIMEOUT_SECONDS if is_lobby else DEFAULT_RUNTIME_STARTUP_TIMEOUT_SECONDS
    )
    policy_secrets = _policy_secrets_from_env()
    player_cpu_request = os.environ.get("COWORLD_PLAYER_CPU_REQUEST", DEFAULT_PLAYER_CPU_REQUEST)
    player_memory_request = os.environ.get("COWORLD_PLAYER_MEMORY_REQUEST", DEFAULT_PLAYER_MEMORY_REQUEST)
    # Empty (the default) means no CPU limit: a player pod may burst to the whole node, so it
    # sees 8/12/16 cores depending on placement. A declared limit caps every player pod here.
    player_cpu_limit = os.environ.get("COWORLD_PLAYER_CPU_LIMIT", "")
    player_connect_timeout_seconds = float(
        job.game_config["player_connect_timeout_seconds"]
        if "player_connect_timeout_seconds" in job.game_config
        else DEFAULT_PLAYER_CONNECT_TIMEOUT_SECONDS
    )
    child_names: list[str] = []
    # Detection-time record of player containers that failed and became dead seats: teardown log
    # collection falls back to it when the pod itself is gone by then (terminated-pod GC).
    dead_seat_statuses: dict[int, PlayerRuntimeStatus] = {}
    artifact_server = _start_player_artifact_upload_server(tokens)
    networking_v1 = client.NetworkingV1Api(api_client) if egress_enforcement_enabled else None

    try:
        _create_game_service(core_v1, namespace, service_name, job_id, owner_references)
        game_pod_ip = None
        if networking_v1 is not None:
            game_pod_ip = os.environ["POD_IP"]
            relay_port = urlsplit(os.environ["COWORLD_EGRESS_RELAY_URL"]).port
            if relay_port is None:
                raise ValueError("COWORLD_EGRESS_RELAY_URL must include the relay Service port")
            networking_v1.create_namespaced_network_policy(
                namespace=namespace,
                body=client.V1NetworkPolicy(
                    metadata=client.V1ObjectMeta(
                        name=f"{service_name}-player-egress",
                        namespace=namespace,
                        owner_references=[
                            client.V1OwnerReference(
                                api_version="batch/v1",
                                kind="Job",
                                name=os.environ["JOB_NAME"],
                                uid=os.environ["JOB_UID"],
                                controller=True,
                            )
                        ],
                    ),
                    spec=client.V1NetworkPolicySpec(
                        pod_selector=client.V1LabelSelector(
                            match_labels={
                                "job-id": job_id,
                                "coworld-component": "player",
                                COWORLD_EGRESS_ENFORCED_LABEL: "true",
                            }
                        ),
                        policy_types=["Egress"],
                        egress=[
                            client.V1NetworkPolicyEgressRule(
                                to=[
                                    client.V1NetworkPolicyPeer(
                                        pod_selector=client.V1LabelSelector(
                                            match_labels={"job-id": job_id, "coworld-component": "game"}
                                        )
                                    )
                                ],
                                ports=[
                                    client.V1NetworkPolicyPort(protocol="TCP", port=GAME_PORT),
                                    client.V1NetworkPolicyPort(protocol="TCP", port=PLAYER_ARTIFACT_PORT),
                                ],
                            ),
                            client.V1NetworkPolicyEgressRule(
                                to=[
                                    client.V1NetworkPolicyPeer(
                                        pod_selector=client.V1LabelSelector(match_labels={"app": "egress-relay"})
                                    )
                                ],
                                ports=[
                                    client.V1NetworkPolicyPort(
                                        protocol="TCP",
                                        port=relay_port,
                                    )
                                ],
                            ),
                        ],
                    ),
                ),
            )
        _wait_for_health(core_v1, namespace, pod_name, timeout_seconds=timeout_seconds)
        game_ready = time.monotonic()
        timings.game_boot_s = game_ready - worker_start
        upload_timings(timings)
        player_launch_start = time.monotonic()
        if job.players:
            _require_http_ok(_player_client_url(0, tokens[0]))
            asyncio.run(_require_bad_player_rejected(f"ws://127.0.0.1:{GAME_PORT}/player?slot=0&token=bad"))
        _require_http_ok(f"http://127.0.0.1:{GAME_PORT}/client/global")

        for slot, player in policy_players:
            name = f"{service_name}-player-{slot}"
            child_names.append(name)
            _create_player_pod(
                core_v1,
                namespace,
                name,
                slot,
                tokens[slot],
                player,
                policy_secrets.get(slot, {}),
                job_id,
                service_name,
                player_cpu_request,
                player_memory_request,
                player_cpu_limit,
                owner_references,
                game_pod_ip=game_pod_ip,
            )
        players_launched = time.monotonic()
        timings.player_launch_s = players_launched - player_launch_start
        upload_timings(timings)
        player_start_deadline = time.monotonic() + min(timeout_seconds, player_connect_timeout_seconds)
        first_step_start = time.monotonic()

        asyncio.run(
            _require_global_message(
                f"ws://127.0.0.1:{GAME_PORT}/global",
                timeout_seconds=timeout_seconds,
                startup_timeout_seconds=startup_timeout_seconds,
                # Hold the viewer connection open while proving every player process started.
                # Some games begin as soon as the last player connects and may not accept a
                # new viewer handshake once gameplay is consuming the server event loop.
                on_connected=lambda: _ensure_player_pods_started(
                    core_v1,
                    namespace,
                    child_names,
                    timeout_seconds=max(0.0, player_start_deadline - time.monotonic()),
                    player_images={slot: player.image for slot, player in policy_players},
                    dead_seat_statuses=dead_seat_statuses,
                ),
                on_connect_failure=lambda: _raise_if_player_pod_failed(core_v1, namespace, child_names),
                require_pong=job.episode_tags.get("source") == CERTIFICATION_EPISODE_SOURCE,
            )
        )
        first_step = time.monotonic()
        timings.first_step_s = first_step - first_step_start
        upload_timings(timings)
        gameplay_start = time.monotonic()
        _wait_for_episode_artifacts(
            artifacts,
            core_v1,
            namespace,
            pod_name,
            child_names,
            player_count=len(job.players),
            timeout_seconds=timeout_seconds,
            require_replay=os.environ.get("REPLAY_URI") is not None,
        )
        gameplay_done = time.monotonic()
        timings.gameplay_s = gameplay_done - gameplay_start
        upload_timings(timings)
        _validate_results_file(artifacts.results_path, job.results_schema)
        if job.episode_tags.get("source") == CERTIFICATION_EPISODE_SOURCE:
            _wait_for_players_to_complete(
                core_v1,
                namespace,
                child_names,
                timeout_seconds=DEFAULT_PLAYER_EXIT_TIMEOUT_SECONDS,
            )
    finally:
        _collect_logs(core_v1, namespace, pod_name, child_names, artifacts, dead_seat_statuses=dead_seat_statuses)
        _delete_child_resources(core_v1, namespace, service_name, child_names)
        if artifact_server is not None:
            artifact_server.shutdown()
            artifact_server.server_close()


def _load_incluster_config(*, egress_enforcement_enabled: bool) -> client.ApiClient:
    # kubernetes>=36.0.2 stores the service-account token under the
    # 'BearerToken' api_key the generated client reads, and its refresh hook
    # keeps that key current across kubelet token rotations. Normalizing the
    # key ourselves here would fight that hook (it rewrites the value with a
    # "bearer " prefix on refresh), so this must stay a plain load.
    config.load_incluster_config()
    # Back off on API Priority & Fairness 429s (etcd throttle) rather than failing the
    # episode. Setting .retries on the default Configuration is orthogonal to the api_key
    # the refresh hook manages. Kept self-contained here because this public package has no
    # internal deps (the backend applies the same policy via runtime.kubernetes.k8s_retry).
    default = client.Configuration.get_default_copy()
    default.retries = Retry(  # type: ignore[assignment]
        total=5,
        backoff_factor=0.5,
        backoff_max=10.0,
        status_forcelist=(429, 500, 502, 503, 504),
        respect_retry_after_header=True,
        allowed_methods=None,
    )
    if egress_enforcement_enabled:
        default.host = f"https://{_KUBERNETES_API_SERVICE_HOST}"
        refresh_api_key = cast(Any, default).refresh_api_key_hook
        assert refresh_api_key is not None

        def refresh_api_key_without_restoring_service_ip(configuration: client.Configuration) -> None:
            refresh_api_key(configuration)
            configuration.host = f"https://{_KUBERNETES_API_SERVICE_HOST}"
            cast(Any, configuration).refresh_api_key_hook = refresh_api_key_without_restoring_service_ip

        cast(Any, default).refresh_api_key_hook = refresh_api_key_without_restoring_service_ip
    client.Configuration.set_default(default)
    api_client = client.ApiClient(default)
    if egress_enforcement_enabled:
        api_client.rest_client.pool_manager = urllib3.ProxyManager(
            proxy_url=os.environ["COWORLD_EGRESS_RELAY_URL"],
            num_pools=4,
            maxsize=default.connection_pool_maxsize,
            cert_reqs=ssl.CERT_REQUIRED,
            ca_certs=default.ssl_ca_cert,
            retries=default.retries,
        )
    return api_client


def _owner_references() -> list[client.V1OwnerReference]:
    return [
        client.V1OwnerReference(
            api_version="v1",
            kind="Pod",
            name=os.environ["POD_NAME"],
            uid=os.environ["POD_UID"],
        )
    ]


def _create_game_service(
    core_v1,
    namespace: str,
    service_name: str,
    job_id: str,
    owner_references: list[client.V1OwnerReference],
) -> client.V1Service:
    ports = [client.V1ServicePort(name="http", port=GAME_PORT, target_port=GAME_PORT)]
    human_player_proxy_port = os.environ.get("COWORLD_HUMAN_PLAYER_PROXY_PORT")
    if human_player_proxy_port is not None:
        proxy_port = int(human_player_proxy_port)
        ports.append(client.V1ServicePort(name="human-player", port=proxy_port, target_port=proxy_port))
    if os.environ.get("PLAYER_ARTIFACT_UPLOAD_URLS") is not None and os.environ.get("COWORLD_EGRESS_RELAY_URL"):
        ports.append(
            client.V1ServicePort(name="player-artifact", port=PLAYER_ARTIFACT_PORT, target_port=PLAYER_ARTIFACT_PORT)
        )
    service = client.V1Service(
        metadata=client.V1ObjectMeta(
            name=service_name,
            namespace=namespace,
            owner_references=owner_references,
        ),
        spec=client.V1ServiceSpec(
            selector={"job-id": job_id, "coworld-component": "game"},
            ports=ports,
        ),
    )
    return cast(client.V1Service, core_v1.create_namespaced_service(namespace=namespace, body=service))


def _create_player_pod(
    core_v1,
    namespace: str,
    name: str,
    slot: int,
    token: str,
    player: PlayerLaunchSpec,
    policy_secret_env: Mapping[str, str],
    job_id: str,
    service_name: str,
    player_cpu_request: str,
    player_memory_request: str,
    player_cpu_limit: str,
    owner_references: list[client.V1OwnerReference],
    *,
    game_pod_ip: str | None = None,
) -> None:
    command, args = _command_args(player.run)
    bedrock_enablement = resolve_player_bedrock(policy_secret_env)
    # A CPU limit caps compute but does NOT change what os.cpu_count()/nproc report (those read
    # the host's /proc/cpuinfo), so a policy that sizes its math-library thread pools off the CPU
    # count would still spawn one-per-node-core and thrash against the quota. Pin the standard
    # thread-pool env to the limit so the player behaves like an N-core box on any node size; the
    # author's own env still wins if they set these explicitly.
    player_env = _player_thread_pool_env(player_cpu_limit) | dict(player.env) | dict(policy_secret_env)
    uses_bedrock = bedrock_enablement.enabled
    uses_sidecar = uses_bedrock and os.environ.get("COWORLD_LOCAL_DEV") != "true"
    if uses_sidecar:
        bedrock_sidecar_port = int(os.environ["BEDROCK_SIDECAR_PORT"])
        # Strip both the direct-access env and the reserved sidecar keys from the user's
        # policy/secret env, then apply platform-owned Bedrock app env LAST so it wins.
        # USE_BEDROCK remains as the public enablement contract; endpoint/credential env
        # routes the actual call through the sidecar.
        player_env = {
            key: value
            for key, value in player_env.items()
            if key not in _DIRECT_BEDROCK_APP_ENV and key not in RESERVED_SIDECAR_APP_ENV
        }
        endpoint_env: dict[str, str] = {
            cast(str, ev.name): cast(str, ev.value)
            for ev in bedrock_app_endpoint_env(bedrock_sidecar_port, os.environ["COWORLD_BEDROCK_REGION"])
        }
        player_env = player_env | {"USE_BEDROCK": "true"} | endpoint_env
    elif uses_bedrock:
        bedrock_region = os.environ["COWORLD_BEDROCK_REGION"]
        player_env = {"AWS_REGION": bedrock_region, "AWS_DEFAULT_REGION": bedrock_region} | player_env
    player_ws_url = _player_service_ws_url(service_name, slot, token)
    player_artifact_upload_url = _player_artifact_upload_url(slot, service_name, token)
    artifact_env_vars = (
        [client.V1EnvVar(name="COWORLD_PLAYER_ARTIFACT_UPLOAD_URL", value=player_artifact_upload_url)]
        if player_artifact_upload_url is not None
        else []
    )
    player_bedrock_metadata = CoworldEpisodeBedrockMetadata.model_validate_json(
        os.environ["BEDROCK_REQUEST_METADATA"]
    ).model_copy(
        update={
            "metadata_origin": "coworld_runner",
            "role": "player",
            "slot": str(slot),
            "image_digest": resolve_image_attribution_key(player.image),
        }
    )
    metadata_env_vars = [
        client.V1EnvVar(
            name="BEDROCK_REQUEST_METADATA",
            value=serialize_bedrock_request_metadata(player_bedrock_metadata),
        )
    ]
    pod_annotations = {"karpenter.sh/do-not-disrupt": "true"}
    pod_volumes: list[client.V1Volume] | None = None
    containers: list[client.V1Container] = [
        client.V1Container(
            name="player",
            image=player.image,
            image_pull_policy=_player_image_pull_policy(player.image),
            command=command,
            args=args,
            env=[
                *_env_vars(player_env),
                client.V1EnvVar(name="COWORLD_PLAYER_WS_URL", value=player_ws_url),
                client.V1EnvVar(name="COGAMES_ENGINE_WS_URL", value=player_ws_url),
                *artifact_env_vars,
                *metadata_env_vars,
            ],
            resources=client.V1ResourceRequirements(
                requests={"cpu": player_cpu_request, "memory": player_memory_request},
                # CPU limit only: a memory limit would risk OOM-killing existing players.
                limits={"cpu": player_cpu_limit} if player_cpu_limit else None,
            ),
            security_context=client.V1SecurityContext(
                allow_privilege_escalation=False,
                capabilities=client.V1Capabilities(drop=["ALL"]),
                seccomp_profile=client.V1SeccompProfile(type="RuntimeDefault"),
            ),
        )
    ]
    # The game is healthy on loopback before this pod is created, but Kubernetes service
    # endpoints can lag that signal. Do not start a one-shot player until the service path
    # it will actually use is reachable.
    init_containers = [
        client.V1Container(
            name="wait-for-game-service",
            image=os.environ["COWORLD_COORDINATOR_IMAGE"],
            image_pull_policy="IfNotPresent",
            command=["python", "-c", _WAIT_FOR_GAME_SERVICE_SCRIPT],
            env=[
                client.V1EnvVar(
                    name="COWORLD_GAME_HOST",
                    value=service_name,
                ),
                client.V1EnvVar(
                    name="COWORLD_GAME_PORT",
                    value=str(GAME_PORT),
                ),
                client.V1EnvVar(
                    name="COWORLD_GAME_WAIT_TIMEOUT_SECONDS",
                    value=os.environ["COWORLD_TIMEOUT_SECONDS"],
                ),
            ],
        )
    ]
    # Native sidecar: an initContainer with restartPolicy=Always, NOT a regular container —
    # a regular container running the long-lived proxy would keep this restartPolicy=Never pod
    # Running after the player exits instead of letting it reach a terminal phase.
    if uses_sidecar:
        # Skip the player app AND the sidecar: the sidecar self-provides its full IRSA env, so
        # the webhook must not also inject a conflicting token path.
        pod_annotations["eks.amazonaws.com/skip-containers"] = f"player,{BEDROCK_SIDECAR_CONTAINER_NAME}"
        prompt_prefix_sample_rate = float(os.environ.get("BEDROCK_SIDECAR_PROMPT_PREFIX_SAMPLE_RATE", "0"))
        egress_relay_url = os.environ.get("BEDROCK_SIDECAR_EGRESS_RELAY_URL") or None
        pod_volumes = [bedrock_sidecar_token_volume(prompt_prefix_measurement=prompt_prefix_sample_rate > 0)]
        init_containers.append(
            build_bedrock_sidecar(
                metadata=player_bedrock_metadata.model_copy(update={"metadata_origin": "bedrock_sidecar"}),
                region=os.environ["COWORLD_BEDROCK_REGION"],
                listen_port=bedrock_sidecar_port,
                upstream_endpoint=os.environ.get("BEDROCK_SIDECAR_UPSTREAM_ENDPOINT") or None,
                image=os.environ["BEDROCK_SIDECAR_IMAGE"],
                role_arn=os.environ["BEDROCK_SIDECAR_ROLE_ARN"],
                # Player-side sidecars persist completion records to the same S3 sink as the
                # game sidecar; the dispatcher forwards these into the worker env (which this
                # runner inherits). Unset bucket keeps the sidecar log-only.
                completions_bucket=os.environ.get("BEDROCK_SIDECAR_COMPLETIONS_BUCKET") or None,
                completions_prefix=os.environ.get("BEDROCK_SIDECAR_COMPLETIONS_PREFIX", "sidecar-completions"),
                flush_records=int(os.environ.get("BEDROCK_SIDECAR_FLUSH_RECORDS", "200")),
                flush_seconds=float(os.environ.get("BEDROCK_SIDECAR_FLUSH_SECONDS", "30.0")),
                # Set on every worker by the dispatcher. Defaulted rather than indexed
                # because app_backend and the coordinator image roll out separately: in
                # the window where an app_backend that predates this change dispatches a
                # newer coordinator, a KeyError here would fail the whole episode. The
                # default matches BedrockSidecarConfig.request_limit_per_minute, so a pod
                # in that window is still bounded.
                request_limit_per_minute=int(os.environ.get("BEDROCK_SIDECAR_REQUEST_LIMIT_PER_MINUTE", "30")),
                llm_relay_s3_bucket=os.environ.get("BEDROCK_SIDECAR_LLM_RELAY_S3_BUCKET") or None,
                llm_relay_s3_prefix=os.environ.get("BEDROCK_SIDECAR_LLM_RELAY_S3_PREFIX", "llm-relay"),
                llm_debug_body_s3_bucket=os.environ.get("BEDROCK_SIDECAR_LLM_DEBUG_BODY_S3_BUCKET") or None,
                openrouter_capture_payloads=(
                    os.environ.get("BEDROCK_SIDECAR_OPENROUTER_CAPTURE_PAYLOADS", "true") == "true"
                ),
                # League-configured per-episode per-player-pod LLM spend limit, forwarded
                # by the dispatcher; the sidecar enforces it.
                spend_limit_usd=os.environ.get("BEDROCK_SIDECAR_SPEND_LIMIT_USD") or None,
                # Server-snapshotted per-model USD rates, forwarded by the dispatcher so
                # the sidecar meters spend with the same rates the server reports.
                pricing_json=os.environ.get("BEDROCK_SIDECAR_PRICING_JSON") or None,
                prompt_prefix_sample_rate=prompt_prefix_sample_rate,
                openrouter_key_secret_name=os.environ.get("COWORLD_OPENROUTER_KEY_SECRET_NAME"),
                openrouter_model_allowlist=(
                    json.loads(os.environ["COWORLD_OPENROUTER_MODEL_ALLOWLIST"])
                    if "COWORLD_OPENROUTER_MODEL_ALLOWLIST" in os.environ
                    else None
                ),
                openrouter_model_aliases=(
                    json.loads(os.environ["COWORLD_OPENROUTER_MODEL_ALIASES"])
                    if "COWORLD_OPENROUTER_MODEL_ALIASES" in os.environ
                    else None
                ),
                openrouter_allowlist_version=os.environ.get("COWORLD_OPENROUTER_ALLOWLIST_VERSION"),
                egress_relay_url=egress_relay_url,
            )
        )
    enforced = os.environ.get("COWORLD_EGRESS_ENFORCEMENT_ENABLED") == "true"
    host_aliases = None
    if enforced:
        if game_pod_ip is None:
            raise ValueError("game_pod_ip is required when Coworld egress enforcement is enabled")
        relay_host = urlsplit(os.environ["COWORLD_EGRESS_RELAY_URL"]).hostname
        if relay_host is None:
            raise ValueError("COWORLD_EGRESS_RELAY_URL must include the relay Service host")
        host_aliases = [
            client.V1HostAlias(ip=game_pod_ip, hostnames=[service_name]),
            client.V1HostAlias(
                ip=os.environ["COWORLD_EGRESS_RELAY_IP"],
                hostnames=[relay_host],
            ),
        ]
    pod = client.V1Pod(
        metadata=client.V1ObjectMeta(
            name=name,
            namespace=namespace,
            annotations=pod_annotations,
            # softmax.com/job-id is the key activated as an AWS cost allocation tag: AWS imports
            # pod labels verbatim into a keyspace that is payer-global and shared with ordinary
            # resource tags, where a bare "job-id" would be collision-prone. Both spellings are
            # written for now -- bare "job-id" is still what the game Service selects on and what
            # event_processor maps pods to jobs with. Spelled out rather than imported from
            # app_backend's config: the coworld-independence import contract forbids that
            # direction, so it must stay in sync with job_runner/config.py.
            labels={
                "job-id": job_id,
                "softmax.com/job-id": job_id,
                "coworld-component": "player",
                "coworld-player-slot": str(slot),
                **({COWORLD_EGRESS_ENFORCED_LABEL: "true"} if enforced else {}),
                # coworld-id / league-id / coworld-source are AWS cost-attribution labels, forwarded by the
                # dispatcher through the worker env so player pods carry the same identity
                # as the game pod. League-less episodes get no COWORLD_LEAGUE_ID.
                **{
                    label: value
                    for label, env_name in (
                        ("coworld-id", "COWORLD_ID"),
                        ("league-id", "COWORLD_LEAGUE_ID"),
                        ("coworld-source", "COWORLD_SOURCE"),
                    )
                    if (value := os.environ.get(env_name))
                },
            },
            owner_references=owner_references,
        ),
        spec=client.V1PodSpec(
            restart_policy="Never",
            service_account_name=_player_service_account_name(bedrock_enablement),
            automount_service_account_token=False,
            host_aliases=host_aliases,
            node_selector=_workload_node_selector(),
            tolerations=_workload_tolerations(),
            volumes=pod_volumes,
            init_containers=init_containers,
            containers=containers,
        ),
    )
    core_v1.create_namespaced_pod(namespace=namespace, body=pod)


def _player_image_pull_policy(image: str) -> str:
    """Digest-pinned (@sha256:) player images are immutable, so IfNotPresent skips the
    registry round-trip on warm nodes. The dispatcher sets the env override for local dev,
    where images are bare tags that only exist on the node."""
    override = os.environ.get("COWORLD_PLAYER_IMAGE_PULL_POLICY")
    if override:
        return override
    return "IfNotPresent" if "@sha256:" in image else "Always"


def _player_artifact_upload_url(slot: int, service_name: str, token: str) -> str | None:
    raw = os.environ.get("PLAYER_ARTIFACT_UPLOAD_URLS")
    if raw is None:
        return None
    target = json.loads(raw).get(str(slot))
    if target is None:
        return None
    if os.environ.get("COWORLD_EGRESS_RELAY_URL"):
        return f"http://{service_name}:{PLAYER_ARTIFACT_PORT}/player-artifact/{slot}/{token}"
    return target


def _player_service_account_name(bedrock_enablement: BedrockEnablement) -> str | None:
    if bedrock_enablement.enabled:
        return _BEDROCK_SERVICE_ACCOUNT
    return None


def _policy_secrets_from_env() -> dict[int, dict[str, str]]:
    secrets_uri = os.environ.pop("POLICY_SECRETS_URI", None)
    if secrets_uri is None:
        return {}
    bundle = json.loads(read_data(secrets_uri))
    return {int(position): secret_env for position, secret_env in bundle["policies"].items()}


def _wait_for_health(core_v1, namespace: str, pod_name: str, *, timeout_seconds: float) -> None:
    deadline = time.monotonic() + timeout_seconds
    url = f"http://127.0.0.1:{GAME_PORT}/healthz"
    while time.monotonic() < deadline:
        _raise_if_game_terminated(core_v1, namespace, pod_name)
        try:
            response = httpx.get(url, timeout=1.0)
            if response.status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(_HEALTH_POLL_SECONDS)
    raise RunnerEpisodeError(f"Timed out waiting for {url}", error_type="game_unhealthy")


def _wait_for_episode_artifacts(
    artifacts: EpisodeArtifacts,
    core_v1,
    namespace: str,
    pod_name: str,
    player_pod_names: list[str] | None = None,
    *,
    player_count: int,
    timeout_seconds: float,
    require_replay: bool,
) -> None:
    # The game owns whether a player failure ends an episode. Required output artifacts
    # win; otherwise a game may publish a typed terminal failure through player_failure.json.
    # Player pod state remains a timeout fallback for games that do not make that choice.
    deadline = time.monotonic() + timeout_seconds
    expected = (artifacts.results_path, artifacts.replay_path) if require_replay else (artifacts.results_path,)
    while time.monotonic() < deadline:
        missing = [path for path in expected if not path.exists()]

        if not missing:
            return

        _raise_if_game_declared_player_failure(artifacts, expected, player_count=player_count)

        exit_code = _game_container_exit_code(core_v1, namespace, pod_name)

        if exit_code is not None:
            # Re-check the declaration AFTER observing the exit: a game that
            # declares a player failure writes player_failure.json and then
            # exits non-zero, and both can land between this iteration's
            # declaration check above and the exit-code read. Blaming the
            # exit first would convert an attributed player_error into an
            # unattributed game_unhealthy — exactly the everyone-punished /
            # no-DQ-strikes outcome the declaration protocol exists to avoid.
            _raise_if_game_declared_player_failure(artifacts, expected, player_count=player_count)
            if exit_code != 0:
                raise RunnerEpisodeError(f"Game container exited with code {exit_code}", error_type="game_unhealthy")
            missing = [path for path in expected if not path.exists()]
            if not missing:
                return
            _raise_if_game_declared_player_failure(artifacts, expected, player_count=player_count)
            missing_list = ", ".join(str(path) for path in missing)
            if artifacts.results_path in missing:
                raise RunnerEpisodeError(
                    f"Game container exited before writing results.json: {artifacts.results_path}",
                    error_type="results_missing",
                )
            raise RunnerEpisodeError(
                f"Game container exited before writing required replay artifact(s): {missing_list}",
                error_type="replay_missing",
            )

        time.sleep(_ARTIFACT_POLL_SECONDS)
    missing = [path for path in expected if not path.exists()]
    if not missing:
        return
    _raise_if_game_declared_player_failure(artifacts, expected, player_count=player_count)
    _raise_if_player_pod_failed(core_v1, namespace, player_pod_names or ())
    expected_list = ", ".join(str(path) for path in expected)
    raise RunnerEpisodeError(
        f"Timed out waiting for game container to finish writing episode artifact(s): {expected_list}",
        error_type="episode_timeout",
    )


def _player_pod_slot(player_pod_name: str) -> int:
    suffix = player_pod_name.rpartition("-player-")[2]
    if not suffix.isdigit():
        raise ValueError(f"Player pod name does not end in '-player-<slot>': {player_pod_name}")
    return int(suffix)


def _ensure_player_pods_started(
    core_v1,
    namespace: str,
    player_pod_names: tuple[str, ...] | list[str],
    *,
    timeout_seconds: float,
    player_images: Mapping[int, str] | None = None,
    dead_seat_statuses: dict[int, PlayerRuntimeStatus] | None = None,
) -> None:
    """Wait for every original player container to start or fail.

    Each player pod owns a one-shot game slot credential. Kubernetes status can lag the process
    long enough for it to acquire that slot, so replacing a waiting or vanished pod could start a
    second process while the original still owns the slot. Infrastructure retries therefore
    create a fresh episode instead of replacing player pods inside a live episode. Once a process
    has started, a later 404 is inconclusive because terminated-pod GC may have reaped it.

    A player container that fails (non-zero exit, or a waiting reason that means the policy
    image itself is broken) is that seat's own loss, not the episode's: the seat is recorded in
    ``dead_seat_statuses`` and logged, and the gate stops waiting for it. The game owns the
    silent seat from there — its player-connect window starts the episode without the missing
    join, and the episode plays out for the other seats. Only Kubernetes failing to run a
    healthy pod at all (never scheduled, status forever pending) stays fatal, because those
    pods got no chance to play and infrastructure should retry with a fresh episode.
    """
    deadline = time.monotonic() + timeout_seconds
    started: set[str] = set()
    dead: set[str] = set()
    while True:
        waiting_reasons: list[str] = []
        for player_pod_name in player_pod_names:
            if player_pod_name in dead:
                continue
            slot = _player_pod_slot(player_pod_name)
            try:
                player_pod = core_v1.read_namespaced_pod(name=player_pod_name, namespace=namespace)
            except ApiException as exc:
                if exc.status != 404:
                    raise
                if player_pod_name in started:
                    continue
                waiting_reasons.append(f"slot {slot}: pod {player_pod_name} not found")
                continue
            failure = _player_container_failure(player_pod, player_pod_name, slot)
            if failure is not None:
                dead.add(player_pod_name)
                failure_status, failure_message = failure
                image = (player_images or {}).get(slot)
                logger.error(
                    "Player slot %s%s failed and plays the episode as a dead seat: %s",
                    slot,
                    f" (policy image {image})" if image else "",
                    failure_message,
                )
                if dead_seat_statuses is not None:
                    dead_seat_statuses[slot] = failure_status
                continue
            if _container_has_started(player_pod, "player"):
                started.add(player_pod_name)
            if player_pod_name in started:
                continue
            reason = _player_waiting_reason(player_pod) or "never scheduled"
            waiting_reasons.append(f"slot {slot}: {reason}")
        if not waiting_reasons:
            return
        if time.monotonic() >= deadline:
            raise RunnerEpisodeError(
                "Kubernetes did not start every player process before the game's player-connect timeout ("
                + "; ".join(waiting_reasons)
                + ")",
                error_type="player_never_started",
            )
        time.sleep(_ARTIFACT_POLL_SECONDS)


def _player_waiting_reason(pod) -> str | None:
    for status in pod.status.container_statuses or []:
        if status.name != "player":
            continue
        waiting = status.state.waiting
        if waiting is not None:
            return waiting.reason or "waiting"
    return None


def _raise_if_player_pod_failed(core_v1, namespace: str, player_pod_names: tuple[str, ...] | list[str]) -> None:
    """Attribute an already-failed episode to a crashed player, if one crashed.

    Only called on paths where the episode cannot complete anyway (viewer connect failure,
    artifact timeout). A live player crash during a healthy episode is a dead seat, not an
    episode failure — see _ensure_player_pods_started.
    """
    for player_pod_name in player_pod_names:
        slot = _player_pod_slot(player_pod_name)
        try:
            player_pod = core_v1.read_namespaced_pod(name=player_pod_name, namespace=namespace)
        except ApiException as exc:
            if exc.status == 404:
                continue
            raise
        failure = _player_container_failure(player_pod, player_pod_name, slot)
        if failure is not None:
            raise PlayerPodFailure(slot, failure[1])


def _player_container_failure(player_pod, player_pod_name: str, slot: int) -> tuple[PlayerRuntimeStatus, str] | None:
    """Detect a failed player container: (runtime status, human-readable message), or None."""
    for status in player_pod.status.container_statuses or []:
        if status.name != "player":
            continue
        state = status.state
        terminated = state.terminated
        if terminated is None and status.last_state is not None:
            terminated = status.last_state.terminated
        if terminated is not None:
            if terminated.exit_code == 0:
                continue
            parts = [f"Player pod {player_pod_name} for slot {slot} terminated with exit code {terminated.exit_code}"]
            parts.extend(part for part in (terminated.reason, terminated.message) if part)
            return (
                PlayerRuntimeStatus(
                    slot=slot,
                    state="exited",
                    exit_code=terminated.exit_code,
                    reason=terminated.reason,
                    finished_at=terminated.finished_at,
                ),
                ": ".join(parts),
            )
        waiting = state.waiting
        waiting_reason = waiting.reason if waiting is not None else None
        if waiting_reason in _PLAYER_WAITING_POLICY_FAILURE_REASONS:
            parts = [f"Player pod {player_pod_name} for slot {slot} waiting: {waiting_reason}"]
            if waiting.message:
                parts.append(waiting.message)
            return (
                PlayerRuntimeStatus(slot=slot, state="not_started", reason=waiting_reason),
                ": ".join(parts),
            )
    return None


def _wait_for_players_to_complete(
    core_v1,
    namespace: str,
    player_pod_names: tuple[str, ...] | list[str],
    *,
    timeout_seconds: float,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while True:
        pending: list[tuple[int, str]] = []
        for player_pod_name in player_pod_names:
            slot = _player_pod_slot(player_pod_name)
            try:
                player_pod = core_v1.read_namespaced_pod(name=player_pod_name, namespace=namespace)
            except ApiException as exc:
                if exc.status == 404:
                    raise PlayerPodFailure(
                        slot,
                        f"Player pod {player_pod_name} for slot {slot} disappeared before completing certification",
                    ) from exc
                raise
            player_status = next(
                (status for status in player_pod.status.container_statuses or [] if status.name == "player"),
                None,
            )
            terminated = player_status.state.terminated if player_status is not None else None
            if terminated is None:
                pending.append((slot, player_pod_name))
                continue
            if terminated.exit_code != 0:
                parts = [
                    f"Player pod {player_pod_name} for slot {slot} terminated with exit code {terminated.exit_code}"
                ]
                parts.extend(part for part in (terminated.reason, terminated.message) if part)
                raise PlayerPodFailure(slot, ": ".join(parts))
        if not pending:
            return
        if time.monotonic() >= deadline:
            slot, player_pod_name = pending[0]
            raise PlayerPodFailure(
                slot,
                f"Timed out waiting for player pod {player_pod_name} for slot {slot} to complete certification",
            )
        time.sleep(_ARTIFACT_POLL_SECONDS)


def _game_container_exit_code(core_v1, namespace: str, pod_name: str) -> int | None:
    pod = core_v1.read_namespaced_pod(name=pod_name, namespace=namespace)
    for status in pod.status.container_statuses or []:
        if status.name != "game" or status.state.terminated is None:
            continue
        return status.state.terminated.exit_code
    return None


def _raise_if_game_terminated(core_v1, namespace: str, pod_name: str) -> None:
    exit_code = _game_container_exit_code(core_v1, namespace, pod_name)
    if exit_code is not None and exit_code != 0:
        raise RunnerEpisodeError(f"Game container exited with code {exit_code}", error_type="game_unhealthy")


def _collect_logs(
    core_v1,
    namespace: str,
    pod_name: str,
    player_pod_names: list[str],
    artifacts: EpisodeArtifacts,
    *,
    dead_seat_statuses: Mapping[int, PlayerRuntimeStatus] | None = None,
) -> None:
    # Every policy slot gets a log file, and so does the game: when logs cannot be collected
    # (pod already reaped, container never started, log endpoint 404), the file says so.
    # Absence would be indistinguishable from "never existed" downstream — hosted consumers
    # list uploaded artifacts and would silently analyze an incomplete observability set.
    #
    # dead_seat_statuses carries what the start gate observed for player containers that failed
    # mid-episode: episodes now play on past a dead seat, so by teardown the crashed pod may have
    # been reaped and live status alone would report an uninformative "unavailable" for exactly
    # the seat whose exit code matters most.
    game_log = _read_pod_log(core_v1, namespace, pod_name, "game")
    if game_log is None:
        game_log = _log_unavailable(pod_name, "game", "the pod was gone before log collection")
    artifacts.game_stdout_path.write_text(game_log, encoding="utf-8")
    player_statuses: list[PlayerRuntimeStatus] = []
    for player_pod_name in player_pod_names:
        slot = _player_pod_slot(player_pod_name)
        detected = (dead_seat_statuses or {}).get(slot)
        try:
            player_pod = core_v1.read_namespaced_pod(name=player_pod_name, namespace=namespace)
        except (ApiException, HTTPError) as exc:
            player_statuses.append(
                detected
                if detected is not None
                else PlayerRuntimeStatus(
                    slot=slot,
                    state="unavailable",
                    reason="pod_not_found"
                    if isinstance(exc, ApiException) and exc.status == 404
                    else "status_read_failed",
                )
            )
            if isinstance(exc, ApiException) and exc.status == 404:
                message = _log_unavailable(player_pod_name, "player", "the pod was deleted before log collection")
            else:
                message = _log_read_failure(player_pod_name, "player", exc)
            artifacts.policy_log_path(slot).write_text(message, encoding="utf-8")
            continue
        player_container_status = next(
            (status for status in player_pod.status.container_statuses or [] if status.name == "player"),
            None,
        )
        if player_container_status is None:
            player_statuses.append(
                detected
                if detected is not None
                else PlayerRuntimeStatus(slot=slot, state="not_started", reason="container_status_unavailable")
            )
        elif player_container_status.state.terminated is not None:
            terminated = player_container_status.state.terminated
            player_statuses.append(
                PlayerRuntimeStatus(
                    slot=slot,
                    state="exited",
                    exit_code=terminated.exit_code,
                    reason=terminated.reason,
                    finished_at=terminated.finished_at,
                )
            )
        elif player_container_status.state.running is not None:
            player_statuses.append(PlayerRuntimeStatus(slot=slot, state="running"))
        else:
            waiting = player_container_status.state.waiting
            player_statuses.append(
                PlayerRuntimeStatus(
                    slot=slot,
                    state="not_started",
                    reason=waiting.reason if waiting is not None else "pending",
                )
            )
        if not _container_has_started(player_pod, "player"):
            artifacts.policy_log_path(slot).write_text(
                _log_unavailable(player_pod_name, "player", "the player container never started"),
                encoding="utf-8",
            )
            continue
        player_log = _read_pod_log(core_v1, namespace, player_pod_name, "player")
        if player_log is None:
            player_log = _log_unavailable(player_pod_name, "player", "the pod was deleted before log collection")
        artifacts.policy_log_path(slot).write_text(player_log, encoding="utf-8")
    artifacts.player_status_path.write_text(
        PlayerRuntimeStatuses(players=player_statuses).model_dump_json(),
        encoding="utf-8",
    )


def _read_pod_log(core_v1, namespace: str, pod_name: str, container: str) -> str | None:
    try:
        return core_v1.read_namespaced_pod_log(
            name=pod_name,
            namespace=namespace,
            container=container,
            tail_lines=10000,
        )
    except (ApiException, HTTPError) as exc:
        if isinstance(exc, ApiException) and exc.status == 404:
            return None
        return _log_read_failure(pod_name, container, exc)


def _log_read_failure(pod_name: str, container: str, exc: Exception) -> str:
    return f"Failed to collect Kubernetes logs for pod {pod_name} container {container}: {exc}\n"


def _log_unavailable(pod_name: str, container: str, reason: str) -> str:
    return f"No logs collected for pod {pod_name} container {container}: {reason}.\n"


def _container_has_started(pod, container_name: str) -> bool:
    for status in pod.status.container_statuses or []:
        if status.name != container_name:
            continue
        return (
            status.state.running is not None
            or status.state.terminated is not None
            or (status.last_state is not None and status.last_state.terminated is not None)
        )
    return False


def _delete_child_resources(core_v1, namespace: str, service_name: str, pod_names: list[str]) -> None:
    for pod_name in pod_names:
        try:
            core_v1.delete_namespaced_pod(name=pod_name, namespace=namespace)
        except ApiException as exc:
            if exc.status != 404:
                raise
    try:
        core_v1.delete_namespaced_service(name=service_name, namespace=namespace)
    except ApiException as exc:
        if exc.status != 404:
            raise


def _player_client_url(slot: int, token: str) -> str:
    return f"http://127.0.0.1:{GAME_PORT}/client/player?{_player_query(slot, token)}"


def _player_service_ws_url(service_name: str, slot: int, token: str) -> str:
    return f"ws://{service_name}:{GAME_PORT}/player?{_player_query(slot, token)}"


def _player_query(slot: int, token: str) -> str:
    return _episode_player_query(slot, token)


def _env_vars(env: Mapping[str, str]) -> list[client.V1EnvVar]:
    return [client.V1EnvVar(name=key, value=value) for key, value in env.items()]


def _command_args(run: tuple[str, ...]) -> tuple[list[str] | None, list[str] | None]:
    if not run:
        return None, None
    return [run[0]], list(run[1:])


def _workload_node_selector() -> dict[str, str] | None:
    workload_type = os.environ.get("COWORLD_WORKLOAD_TYPE")
    if not workload_type:
        return None
    selector = {"workload-type": workload_type}
    capacity_type = os.environ.get("COWORLD_CAPACITY_TYPE")
    if capacity_type:
        selector["karpenter.sh/capacity-type"] = capacity_type
    return selector


def _workload_tolerations() -> list[client.V1Toleration] | None:
    workload_type = os.environ.get("COWORLD_WORKLOAD_TYPE")
    if not workload_type:
        return None

    return [
        client.V1Toleration(
            key="workload-type",
            operator="Equal",
            value=workload_type,
            effect="NoSchedule",
        )
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("init-config", "run-core-sidecars-v1"))
    args = parser.parse_args()
    if args.command == "init-config":
        init_config_from_env()
    else:
        run_from_env()


if __name__ == "__main__":
    sys.exit(main())
