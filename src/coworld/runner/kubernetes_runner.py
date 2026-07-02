from __future__ import annotations

import argparse
import asyncio
import json
import os
import socketserver
import sys
import threading
import time
import zipfile
import zlib
from io import BytesIO
from pathlib import Path
from typing import Mapping

import httpx
from kubernetes import client, config
from kubernetes.client.rest import ApiException
from kubernetes.utils import parse_quantity

from coworld.runner.bedrock_enablement import BedrockEnablement, resolve_player_bedrock
from coworld.runner.bedrock_sidecar_wiring import (
    BEDROCK_SIDECAR_CONTAINER_NAME,
    RESERVED_SIDECAR_APP_ENV,
    BedrockSidecarAttribution,
    bedrock_app_endpoint_env,
    bedrock_sidecar_token_volume,
    build_bedrock_sidecar,
    resolve_image_attribution_key,
)
from coworld.runner.io import RunnerEpisodeError, RunnerError, read_data, upload_data
from coworld.runner.phase_timings import EpisodePhaseTimings
from coworld.runner.runner import (
    EpisodeArtifacts,
    PlayerLaunchSpec,
    _require_bad_player_rejected,
    _require_global_message,
    _require_http_ok,
    _validate_results_file,
    coworld_game_config,
    generate_tokens,
)
from coworld.runner.runner import (
    _player_query as _episode_player_query,
)
from coworld.types import CoworldEpisodeJobSpec

WORKDIR = Path(os.environ.get("COWORLD_WORKDIR", "/coworld"))
STATE_PATH = WORKDIR / "state.json"
GAME_PORT = int(os.environ.get("COGAME_PORT", "8080"))
HEALTH_PORT = int(os.environ.get("COWORLD_WORKER_HEALTH_PORT", "9090"))
_BEDROCK_SERVICE_ACCOUNT = "episode-runner"
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


def init_config_from_env() -> None:
    job = _read_job_spec()
    tokens = generate_tokens(len(job.players))
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
    try:
        core_timings = _run_kubernetes_episode(
            job,
            artifacts,
            timeout_seconds=float(os.environ.get("COWORLD_TIMEOUT_SECONDS", "3600")),
        )
    except Exception as exc:
        _write_error_info(exc)
        _upload_debug_logs(artifacts)
        raise
    upload_start = time.monotonic()
    _upload_outputs(artifacts)
    _upload_timings(EpisodePhaseTimings(**core_timings, artifact_upload_s=time.monotonic() - upload_start))


def _read_job_spec() -> CoworldEpisodeJobSpec:
    return CoworldEpisodeJobSpec.model_validate_json(read_data(os.environ["JOB_SPEC_URI"]))


def _write_error_info(exc: Exception) -> None:
    error_info_uri = os.environ.get("ERROR_INFO_URI")
    if error_info_uri is None:
        return
    if isinstance(exc, RunnerEpisodeError):
        runner_error = RunnerError(
            error_type=exc.error_type,
            message=str(exc)[:2000],
            failed_policy_index=exc.failed_policy_index,
        )
    else:
        runner_error = RunnerError(error_type="crash", message=str(exc)[:2000])
    upload_data(error_info_uri, runner_error.model_dump_json(), content_type="application/json")


def _upload_debug_logs(artifacts: EpisodeArtifacts) -> None:
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
        upload_data(timings_uri, timings.model_dump_json(), content_type="application/json")


def _upload_outputs(artifacts: EpisodeArtifacts) -> None:
    results_uri = os.environ.get("RESULTS_URI")
    if results_uri is not None:
        upload_data(results_uri, artifacts.results_path.read_bytes(), content_type="application/json")

    replay_uri = os.environ.get("REPLAY_URI")
    if replay_uri is not None:
        upload_data(
            replay_uri,
            zlib.compress(artifacts.replay_path.read_bytes()),
            content_type="application/x-compress",
        )

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
) -> dict[str, float]:
    worker_start = time.monotonic()
    _load_incluster_config()
    core_v1 = client.CoreV1Api()
    namespace = os.environ["JOB_NAMESPACE"]
    service_name = os.environ["COWORLD_SERVICE_NAME"]
    job_id = os.environ["JOB_ID"]
    pod_name = os.environ["POD_NAME"]
    owner_references = _owner_references()
    tokens = json.loads(STATE_PATH.read_text(encoding="utf-8"))["tokens"]
    players = [PlayerLaunchSpec.from_model(player) for player in job.players]
    policy_secrets = _policy_secrets_from_env()
    player_cpu_request = os.environ.get("COWORLD_PLAYER_CPU_REQUEST", DEFAULT_PLAYER_CPU_REQUEST)
    player_memory_request = os.environ.get("COWORLD_PLAYER_MEMORY_REQUEST", DEFAULT_PLAYER_MEMORY_REQUEST)
    # Empty (the default) means no CPU limit: a player pod may burst to the whole node, so it
    # sees 8/12/16 cores depending on placement. A declared limit caps every player pod here.
    player_cpu_limit = os.environ.get("COWORLD_PLAYER_CPU_LIMIT", "")
    child_names: list[str] = []

    try:
        _create_game_service(core_v1, namespace, service_name, job_id, owner_references)
        _wait_for_health(core_v1, namespace, pod_name, timeout_seconds=timeout_seconds)
        game_ready = time.monotonic()
        if players:
            _require_http_ok(_player_client_url(0, tokens[0]))
            asyncio.run(_require_bad_player_rejected(f"ws://127.0.0.1:{GAME_PORT}/player?slot=0&token=bad"))
        _require_http_ok(f"http://127.0.0.1:{GAME_PORT}/client/global")

        for slot, player in enumerate(players):
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
            )
        players_launched = time.monotonic()

        asyncio.run(
            _require_global_message(
                f"ws://127.0.0.1:{GAME_PORT}/global",
                timeout_seconds=timeout_seconds,
                on_connect_failure=lambda: _raise_if_player_pod_failed(core_v1, namespace, child_names),
            )
        )
        first_step = time.monotonic()
        _wait_for_episode_artifacts(
            artifacts,
            core_v1,
            namespace,
            pod_name,
            child_names,
            timeout_seconds=timeout_seconds,
            require_replay=os.environ.get("REPLAY_URI") is not None,
        )
        gameplay_done = time.monotonic()
        _validate_results_file(artifacts.results_path, job.results_schema)
        # A game that tolerates absent seats (connect-timeout auto-start) still writes a normal
        # results.json when its player pods never came up — producing a silent, blank, zero-progress
        # episode that the platform would otherwise record as a success. The orchestrator owns the
        # truth here (it scheduled the pods), so fail loudly with a typed error instead.
        _raise_if_no_players_started(core_v1, namespace, child_names)
        core_timings = {
            "game_boot_s": game_ready - worker_start,
            "player_launch_s": players_launched - game_ready,
            "first_step_s": first_step - players_launched,
            "gameplay_s": gameplay_done - first_step,
        }
    finally:
        _collect_logs(core_v1, namespace, pod_name, child_names, artifacts)
        _delete_child_resources(core_v1, namespace, service_name, child_names)
    return core_timings


def _load_incluster_config() -> None:
    config.load_incluster_config()
    kube_config = client.Configuration.get_default_copy()
    scheme, token = kube_config.api_key["authorization"].split(" ", 1)
    assert scheme.lower() == "bearer"
    kube_config.api_key["BearerToken"] = token
    kube_config.api_key_prefix["BearerToken"] = "Bearer"
    client.Configuration.set_default(kube_config)


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
) -> None:
    service = client.V1Service(
        metadata=client.V1ObjectMeta(
            name=service_name,
            namespace=namespace,
            labels={"coworld-job-id": job_id},
            owner_references=owner_references,
        ),
        spec=client.V1ServiceSpec(
            selector={"job-id": job_id, "coworld-component": "game"},
            ports=[client.V1ServicePort(name="http", port=GAME_PORT, target_port=GAME_PORT)],
        ),
    )
    core_v1.create_namespaced_service(namespace=namespace, body=service)


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
) -> None:
    command, args = _command_args(player.run)
    bedrock_enablement = resolve_player_bedrock(policy_secret_env)
    # A CPU limit caps compute but does NOT change what os.cpu_count()/nproc report (those read
    # the host's /proc/cpuinfo), so a policy that sizes its math-library thread pools off the CPU
    # count would still spawn one-per-node-core and thrash against the quota. Pin the standard
    # thread-pool env to the limit so the player behaves like an N-core box on any node size; the
    # author's own env still wins if they set these explicitly.
    player_env = _player_thread_pool_env(player_cpu_limit) | dict(player.env) | dict(policy_secret_env)
    bedrock_sidecar_enabled = os.environ.get("BEDROCK_SIDECAR_ENABLED") == "true" and bedrock_enablement.enabled
    if bedrock_sidecar_enabled:
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
        endpoint_env = {
            ev.name: ev.value
            for ev in bedrock_app_endpoint_env(bedrock_sidecar_port, os.environ["COWORLD_BEDROCK_REGION"])
        }
        player_env = player_env | {"USE_BEDROCK": "true"} | endpoint_env
    elif bedrock_enablement.enabled:
        bedrock_region = os.environ["COWORLD_BEDROCK_REGION"]
        player_env = {"AWS_REGION": bedrock_region, "AWS_DEFAULT_REGION": bedrock_region} | player_env
    player_ws_url = _player_service_ws_url(service_name, slot, token)
    player_artifact_upload_url = _player_artifact_upload_url(slot)
    artifact_env_vars = (
        [client.V1EnvVar(name="COWORLD_PLAYER_ARTIFACT_UPLOAD_URL", value=player_artifact_upload_url)]
        if player_artifact_upload_url is not None
        else []
    )
    # Tag this player's Bedrock invocations with the coworld/episode (forwarded by
    # the worker) plus its slot, so model-invocation logs attribute player-side LLM
    # usage to a coworld. A player image that uses @cogweb/llm sets it as the
    # Converse requestMetadata; harmless for a non-Bedrock player.
    metadata_base = os.environ.get("BEDROCK_REQUEST_METADATA")
    metadata_env_vars = []
    if metadata_base:
        slot_metadata = json.dumps({**json.loads(metadata_base), "slot": str(slot)})
        metadata_env_vars = [client.V1EnvVar(name="BEDROCK_REQUEST_METADATA", value=slot_metadata)]
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
        )
    ]
    # Native sidecar: an initContainer with restartPolicy=Always, NOT a regular container —
    # a regular container running the long-lived proxy would keep this restartPolicy=Never pod
    # Running after the player exits instead of letting it reach a terminal phase.
    init_containers: list[client.V1Container] | None = None
    if bedrock_sidecar_enabled:
        # Skip the player app AND the sidecar: the sidecar self-provides its full IRSA env, so
        # the webhook must not also inject a conflicting token path.
        pod_annotations["eks.amazonaws.com/skip-containers"] = f"player,{BEDROCK_SIDECAR_CONTAINER_NAME}"
        pod_volumes = [bedrock_sidecar_token_volume()]
        init_containers = [
            build_bedrock_sidecar(
                attribution=BedrockSidecarAttribution(
                    image_digest=resolve_image_attribution_key(player.image),
                    episode_request_id=job_id,
                    role="player",
                    slot=str(slot),
                ),
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
                # League-configured per-episode per-player-pod LLM spend limit, forwarded
                # by the dispatcher; the sidecar enforces it.
                spend_limit_usd=os.environ.get("BEDROCK_SIDECAR_SPEND_LIMIT_USD") or None,
                # Server-snapshotted per-model USD rates, forwarded by the dispatcher so
                # the sidecar meters spend with the same rates the server reports.
                pricing_json=os.environ.get("BEDROCK_SIDECAR_PRICING_JSON") or None,
            )
        ]
    pod = client.V1Pod(
        metadata=client.V1ObjectMeta(
            name=name,
            namespace=namespace,
            annotations=pod_annotations,
            labels={
                "coworld-job-id": job_id,
                "coworld-component": "player",
                "coworld-player-slot": str(slot),
            },
            owner_references=owner_references,
        ),
        spec=client.V1PodSpec(
            restart_policy="Never",
            service_account_name=_player_service_account_name(bedrock_enablement),
            automount_service_account_token=False if bedrock_sidecar_enabled else None,
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


def _player_artifact_upload_url(slot: int) -> str | None:
    """The presigned PUT URL this player slot may upload a single artifact .zip to.

    The dispatcher passes PLAYER_ARTIFACT_UPLOAD_URLS to the worker as a JSON map slot -> url; the
    worker forwards the matching slot's URL into the player pod. The player may upload at any time
    but must finish before the pod is torn down after the game ends.
    """
    raw = os.environ.get("PLAYER_ARTIFACT_UPLOAD_URLS")
    if raw is None:
        return None
    return json.loads(raw).get(str(slot))


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
        time.sleep(0.2)
    raise RunnerEpisodeError(f"Timed out waiting for {url}", error_type="game_unhealthy")


def _wait_for_episode_artifacts(
    artifacts: EpisodeArtifacts,
    core_v1,
    namespace: str,
    pod_name: str,
    player_pod_names: list[str] | None = None,
    *,
    timeout_seconds: float,
    require_replay: bool,
) -> None:
    # Game artifacts win. Player pod failures are attributed only after the game
    # times out without writing the required episode artifacts.
    deadline = time.monotonic() + timeout_seconds
    expected = [artifacts.results_path]
    if require_replay:
        expected.append(artifacts.replay_path)

    while time.monotonic() < deadline:
        missing = [path for path in expected if not path.exists()]

        if not missing:
            return

        exit_code = _game_container_exit_code(core_v1, namespace, pod_name)

        if exit_code is not None:
            if exit_code != 0:
                raise RunnerEpisodeError(f"Game container exited with code {exit_code}", error_type="game_unhealthy")
            missing = [path for path in expected if not path.exists()]
            if not missing:
                return
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

        time.sleep(0.5)
    _raise_if_player_pod_failed(core_v1, namespace, player_pod_names or ())
    expected_list = ", ".join(str(path) for path in expected)
    raise RunnerEpisodeError(
        f"Timed out waiting for game container to finish writing episode artifact(s): {expected_list}",
        error_type="episode_timeout",
    )


def _raise_if_no_players_started(core_v1, namespace: str, player_pod_names: tuple[str, ...] | list[str]) -> None:
    """Fail a degenerate episode where the game wrote results but no player ever joined.

    Connect-timeout-tolerant games auto-start and write a normal results.json even when every
    player pod failed to come up (e.g. a cold image pull lost the race against the connect
    deadline), yielding a blank, zero-progress episode with no error trail. The orchestrator
    scheduled these pods, so it can tell "the policies never started" from k8s state alone —
    independent of any game-specific results shape. Only fires when there are seats to fill and
    not one of them started; a partially-filled episode is left to the game's own scoring.
    """
    if not player_pod_names:
        return
    waiting_reasons: list[str] = []
    for slot, player_pod_name in enumerate(player_pod_names):
        try:
            player_pod = core_v1.read_namespaced_pod(name=player_pod_name, namespace=namespace)
        except ApiException as exc:
            if exc.status == 404:
                waiting_reasons.append(f"slot {slot}: pod {player_pod_name} not found")
                continue
            raise
        if _container_has_started(player_pod, "player"):
            return
        reason = _player_waiting_reason(player_pod) or "never scheduled"
        waiting_reasons.append(f"slot {slot}: {reason}")
    raise RunnerEpisodeError(
        "No player pods started for any seat before the episode ended; "
        "policies never joined the game (" + "; ".join(waiting_reasons) + ")",
        error_type="no_players_connected",
    )


def _player_waiting_reason(pod) -> str | None:
    for status in pod.status.container_statuses or []:
        if status.name != "player":
            continue
        waiting = status.state.waiting
        if waiting is not None:
            return waiting.reason or "waiting"
    return None


def _raise_if_player_pod_failed(core_v1, namespace: str, player_pod_names: tuple[str, ...] | list[str]) -> None:
    for slot, player_pod_name in enumerate(player_pod_names):
        try:
            player_pod = core_v1.read_namespaced_pod(name=player_pod_name, namespace=namespace)
        except ApiException as exc:
            if exc.status == 404:
                continue
            raise
        for status in player_pod.status.container_statuses or []:
            if status.name != "player":
                continue
            state = status.state
            terminated = state.terminated
            if terminated is not None:
                if terminated.exit_code == 0:
                    continue
                parts = [
                    f"Player pod {player_pod_name} for slot {slot} terminated with exit code "
                    f"{terminated.exit_code} before episode artifacts were written"
                ]
                parts.extend(part for part in (terminated.reason, terminated.message) if part)
                raise PlayerPodFailure(slot, ": ".join(parts))
            waiting = state.waiting
            waiting_reason = waiting.reason if waiting is not None else None
            if waiting_reason in _PLAYER_WAITING_POLICY_FAILURE_REASONS:
                parts = [
                    f"Player pod {player_pod_name} for slot {slot} waiting: {waiting_reason} "
                    "before episode artifacts were written"
                ]
                if waiting.message:
                    parts.append(waiting.message)
                raise PlayerPodFailure(slot, ": ".join(parts))


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
) -> None:
    game_log = _read_pod_log(core_v1, namespace, pod_name, "game")
    if game_log is not None:
        artifacts.game_stdout_path.write_text(game_log, encoding="utf-8")
    for slot, player_pod_name in enumerate(player_pod_names):
        try:
            player_pod = core_v1.read_namespaced_pod(name=player_pod_name, namespace=namespace)
        except ApiException as exc:
            if exc.status == 404:
                continue
            artifacts.policy_log_path(slot).write_text(
                _log_read_failure(player_pod_name, "player", exc),
                encoding="utf-8",
            )
            continue
        if not _container_has_started(player_pod, "player"):
            continue
        player_log = _read_pod_log(core_v1, namespace, player_pod_name, "player")
        if player_log is not None:
            artifacts.policy_log_path(slot).write_text(player_log, encoding="utf-8")


def _read_pod_log(core_v1, namespace: str, pod_name: str, container: str) -> str | None:
    try:
        return core_v1.read_namespaced_pod_log(
            name=pod_name,
            namespace=namespace,
            container=container,
            tail_lines=10000,
        )
    except ApiException as exc:
        if exc.status == 404:
            return None
        return _log_read_failure(pod_name, container, exc)


def _log_read_failure(pod_name: str, container: str, exc: ApiException) -> str:
    return f"Failed to collect Kubernetes logs for pod {pod_name} container {container}: {exc}\n"


def _container_has_started(pod, container_name: str) -> bool:
    for status in pod.status.container_statuses or []:
        if status.name != container_name:
            continue
        return status.state.running is not None or status.state.terminated is not None
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
    parser.add_argument("command", choices=("init-config", "run"))
    args = parser.parse_args()
    if args.command == "init-config":
        init_config_from_env()
    else:
        run_from_env()


if __name__ == "__main__":
    sys.exit(main())
