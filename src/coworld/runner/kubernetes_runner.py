from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import zipfile
import zlib
from io import BytesIO
from pathlib import Path
from typing import Mapping

import httpx
from kubernetes import client, config
from kubernetes.client.rest import ApiException

from coworld.runner.io import RunnerError, read_data, upload_data
from coworld.runner.runner import (
    EpisodeArtifacts,
    PlayerLaunchSpec,
    _require_bad_player_rejected,
    _require_global_message,
    _require_http_ok,
    coworld_game_config,
    generate_tokens,
)
from coworld.runner.runner import (
    _player_query as _episode_player_query,
)
from coworld.schema_validation import validate_json_schema
from coworld.types import CoworldEpisodeJobSpec

WORKDIR = Path(os.environ.get("COWORLD_WORKDIR", "/coworld"))
STATE_PATH = WORKDIR / "state.json"
GAME_PORT = 8080
_BEDROCK_SERVICE_ACCOUNT = "episode-runner"


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
    job = _read_job_spec()
    artifacts = EpisodeArtifacts.create(WORKDIR, prefix="coworld-job-")
    try:
        _run_kubernetes_episode(
            job,
            artifacts,
            timeout_seconds=float(os.environ.get("COWORLD_TIMEOUT_SECONDS", "3600")),
        )
    except Exception as exc:
        _write_error_info(exc)
        _upload_debug_logs(artifacts)
        raise
    _upload_outputs(artifacts)


def _read_job_spec() -> CoworldEpisodeJobSpec:
    return CoworldEpisodeJobSpec.model_validate_json(read_data(os.environ["JOB_SPEC_URI"]))


def _write_error_info(exc: Exception) -> None:
    error_info_uri = os.environ.get("ERROR_INFO_URI")
    if error_info_uri is None:
        return
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


def _upload_outputs(artifacts: EpisodeArtifacts) -> None:
    results_uri = os.environ.get("RESULTS_URI")
    if results_uri is not None:
        upload_data(results_uri, artifacts.results_path.read_bytes(), content_type="application/json")

    replay_uri = os.environ.get("REPLAY_URI")
    if replay_uri is not None:
        upload_data(replay_uri, _compress_replay(artifacts).read_bytes(), content_type="application/x-compress")

    debug_uri = os.environ.get("DEBUG_URI")
    if debug_uri is not None:
        upload_data(debug_uri, _zip_logs(artifacts.logs_dir), content_type="application/zip")

    policy_log_urls = os.environ.get("POLICY_LOG_URLS")
    if policy_log_urls is not None:
        for slot, log_uri in json.loads(policy_log_urls).items():
            log_path = artifacts.policy_log_path(int(slot))
            if log_path.exists():
                upload_data(log_uri, log_path.read_bytes(), content_type="text/plain")


def _compress_replay(artifacts: EpisodeArtifacts) -> Path:
    compressed_path = artifacts.workspace / "replay.json.z"
    compressed_path.write_bytes(zlib.compress(artifacts.replay_path.read_bytes()))
    return compressed_path


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
) -> None:
    config.load_incluster_config()
    core_v1 = client.CoreV1Api()
    namespace = os.environ["JOB_NAMESPACE"]
    service_name = os.environ["COWORLD_SERVICE_NAME"]
    job_id = os.environ["JOB_ID"]
    pod_name = os.environ["POD_NAME"]
    owner_references = _owner_references()
    tokens = json.loads(STATE_PATH.read_text(encoding="utf-8"))["tokens"]
    players = [PlayerLaunchSpec.from_model(player) for player in job.players]
    policy_secrets = _policy_secrets_from_env()
    child_names: list[str] = []

    try:
        _create_game_service(core_v1, namespace, service_name, job_id, owner_references)
        _wait_for_health(core_v1, namespace, pod_name, timeout_seconds=timeout_seconds)
        if players:
            _require_http_ok(_player_client_url(0, tokens[0], players[0]))
            asyncio.run(_require_bad_player_rejected(f"ws://127.0.0.1:{GAME_PORT}/player?slot=0&token=bad"))
        _require_http_ok(f"http://127.0.0.1:{GAME_PORT}/clients/global")

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
                owner_references,
            )

        asyncio.run(_require_global_message(f"ws://127.0.0.1:{GAME_PORT}/global", timeout_seconds=timeout_seconds))
        _wait_for_episode_artifacts(
            artifacts,
            core_v1,
            namespace,
            pod_name,
            timeout_seconds=timeout_seconds,
            require_replay=os.environ.get("REPLAY_URI") is not None,
        )
        results = json.loads(artifacts.results_path.read_text(encoding="utf-8"))
        validate_json_schema(results, job.results_schema)
    finally:
        _collect_logs(core_v1, namespace, pod_name, child_names, artifacts)
        _delete_child_resources(core_v1, namespace, service_name, child_names)


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
    owner_references: list[client.V1OwnerReference],
) -> None:
    command, args = _command_args(player.run)
    player_env = dict(player.env) | dict(policy_secret_env)
    pod = client.V1Pod(
        metadata=client.V1ObjectMeta(
            name=name,
            namespace=namespace,
            annotations={"karpenter.sh/do-not-disrupt": "true"},
            labels={
                "coworld-job-id": job_id,
                "coworld-component": "player",
                "coworld-player-slot": str(slot),
            },
            owner_references=owner_references,
        ),
        spec=client.V1PodSpec(
            restart_policy="Never",
            service_account_name=_player_service_account_name(policy_secret_env),
            node_selector=_workload_node_selector(),
            tolerations=_workload_tolerations(),
            containers=[
                client.V1Container(
                    name="player",
                    image=player.image,
                    image_pull_policy=os.environ.get("COWORLD_PLAYER_IMAGE_PULL_POLICY", "Always"),
                    command=command,
                    args=args,
                    env=[
                        *_env_vars(player_env),
                        client.V1EnvVar(
                            name="COGAMES_ENGINE_WS_URL",
                            value=_player_service_ws_url(service_name, slot, token, player),
                        ),
                    ],
                )
            ],
        ),
    )
    core_v1.create_namespaced_pod(namespace=namespace, body=pod)


def _player_service_account_name(policy_secret_env: Mapping[str, str]) -> str | None:
    if "USE_BEDROCK" in policy_secret_env and policy_secret_env["USE_BEDROCK"] == "true":
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
    raise TimeoutError(f"Timed out waiting for {url}")


def _wait_for_episode_artifacts(
    artifacts: EpisodeArtifacts,
    core_v1,
    namespace: str,
    pod_name: str,
    *,
    timeout_seconds: float,
    require_replay: bool,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    expected = [artifacts.results_path]
    if require_replay:
        expected.append(artifacts.replay_path)

    while time.monotonic() < deadline:
        missing = [path for path in expected if not path.exists()]

        if not missing and not require_replay:
            return

        exit_code = _game_container_exit_code(core_v1, namespace, pod_name)

        if exit_code is not None:
            if exit_code != 0:
                raise RuntimeError(f"Game container exited with code {exit_code}")
            missing = [path for path in expected if not path.exists()]
            if not missing:
                return
            missing_list = ", ".join(str(path) for path in missing)
            raise TimeoutError(f"Game container exited before writing episode artifact(s): {missing_list}")

        time.sleep(0.5)
    expected_list = ", ".join(str(path) for path in expected)
    raise TimeoutError(f"Timed out waiting for game container to finish writing episode artifact(s): {expected_list}")


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
        raise RuntimeError(f"Game container exited with code {exit_code}")


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


def _player_client_url(slot: int, token: str, player: PlayerLaunchSpec) -> str:
    return f"http://127.0.0.1:{GAME_PORT}/clients/player?{_player_query(slot, token, player)}"


def _player_service_ws_url(service_name: str, slot: int, token: str, player: PlayerLaunchSpec) -> str:
    return f"ws://{service_name}:{GAME_PORT}/player?{_player_query(slot, token, player)}"


def _player_query(slot: int, token: str, player: PlayerLaunchSpec) -> str:
    return _episode_player_query(slot, token, player)


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
    return {"workload-type": workload_type}


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
