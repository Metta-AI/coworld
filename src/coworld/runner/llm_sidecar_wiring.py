from __future__ import annotations

import json

from kubernetes import client

from coworld.runner.llm_metadata import CoworldLlmMetadata, serialize_llm_request_metadata

LLM_SIDECAR_CONTAINER_NAME = "llm-sidecar"
LLM_SIDECAR_TOKEN_VOLUME_NAME = "llm-sidecar-aws-token"
LLM_SIDECAR_TOKEN_MOUNT_PATH = "/var/run/secrets/llm-sidecar"
LLM_SIDECAR_TOKEN_PATH = "token"
LLM_SIDECAR_TOKEN_FILE = f"{LLM_SIDECAR_TOKEN_MOUNT_PATH}/{LLM_SIDECAR_TOKEN_PATH}"
LLM_SIDECAR_CONTRACT_VERSION = "core-v1"
LLM_SIDECAR_HEALTH_PATH = f"/healthz/{LLM_SIDECAR_CONTRACT_VERSION}"
EGRESS_RELAY_CLIENT_TLS_SECRET_NAME = "egress-relay-client-tls"
EGRESS_RELAY_CLIENT_TLS_VOLUME_NAME = "egress-relay-client-tls"
EGRESS_RELAY_CLIENT_TLS_MOUNT_PATH = "/var/run/secrets/egress-relay"
EGRESS_RELAY_CLIENT_CERT_FILE = f"{EGRESS_RELAY_CLIENT_TLS_MOUNT_PATH}/tls.crt"
EGRESS_RELAY_CLIENT_KEY_FILE = f"{EGRESS_RELAY_CLIENT_TLS_MOUNT_PATH}/tls.key"
EGRESS_RELAY_CA_FILE = f"{EGRESS_RELAY_CLIENT_TLS_MOUNT_PATH}/ca.crt"
COWORLD_EGRESS_ENFORCED_LABEL = "coworld-egress-enforced"
GAME_EGRESS_PROXY_PORT = 3129


# Platform endpoints and placeholder credentials cannot be overridden by policy secrets.
RESERVED_SIDECAR_APP_ENV = frozenset(
    {
        "COWORLD_LLM_ENDPOINT",
        "COWORLD_LLM_ENABLED",
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "OPENAI_BASE_URL",
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "LLM_SIDECAR_CHECKPOINT_ROUTES",
        "COWORLD_CHECKPOINT_ROUTES_SECRET_NAME",
        "COWORLD_LOCAL_CHECKPOINT_ROUTING",
        "COWORLD_LOCAL_ARTIFACT_ENDPOINT_URL",
        "COWORLD_LOCAL_ARTIFACT_ACCESS_KEY_ID",
        "COWORLD_LOCAL_ARTIFACT_SECRET_ACCESS_KEY",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_WEB_IDENTITY_TOKEN_FILE",
        "AWS_ROLE_ARN",
    }
)


def resolve_image_attribution_key(image: str) -> str:
    """Coworld stays app_backend-independent: parse pinned digests, else keep the image ref."""
    digest_marker = "@sha256:"
    if digest_marker in image:
        return f"sha256:{image.split(digest_marker, maxsplit=1)[1]}"
    return image


def egress_relay_client_env(url: str, *, prefix: str) -> list[client.V1EnvVar]:
    return [
        client.V1EnvVar(name=f"{prefix}_EGRESS_RELAY_URL", value=url),
        client.V1EnvVar(name=f"{prefix}_EGRESS_RELAY_CLIENT_CERT_FILE", value=EGRESS_RELAY_CLIENT_CERT_FILE),
        client.V1EnvVar(name=f"{prefix}_EGRESS_RELAY_CLIENT_KEY_FILE", value=EGRESS_RELAY_CLIENT_KEY_FILE),
        client.V1EnvVar(name=f"{prefix}_EGRESS_RELAY_CA_FILE", value=EGRESS_RELAY_CA_FILE),
    ]


def build_llm_sidecar(
    *,
    metadata: CoworldLlmMetadata,
    listen_port: int,
    region: str,
    image: str,
    role_arn: str,
    flush_records: int,
    flush_seconds: float,
    request_limit_per_minute: int,
    llm_relay_s3_bucket: str | None = None,
    llm_relay_s3_prefix: str = "llm-relay",
    llm_debug_body_s3_bucket: str | None = None,
    openrouter_capture_payloads: bool = True,
    spend_limit_usd: str | None = None,
    player_slot_count: int | None = None,
    openrouter_key_secret_name: str | None,
    openrouter_model_allowlist: list[str] | None = None,
    openrouter_allowlist_version: str | None = None,
    egress_relay_url: str | None = None,
    runtime_deadline: str | None = None,
    checkpoint_routes_secret_name: str | None = None,
    local_artifact_endpoint_url: str | None = None,
    local_artifact_access_key_id: str | None = None,
    local_artifact_secret_access_key: str | None = None,
) -> client.V1Container:
    if openrouter_key_secret_name is None and (
        checkpoint_routes_secret_name is None or openrouter_model_allowlist != []
    ):
        raise ValueError("Checkpoint-only sidecars require trusted routes and deny merchant models")
    local_artifacts = local_artifact_endpoint_url is not None
    if local_artifacts and (local_artifact_access_key_id is None or local_artifact_secret_access_key is None):
        raise ValueError("Local artifact storage requires its configured credentials")
    sink_tuning_env = (
        [
            client.V1EnvVar(name="LLM_SIDECAR_FLUSH_RECORDS", value=str(flush_records)),
            client.V1EnvVar(name="LLM_SIDECAR_FLUSH_SECONDS", value=str(flush_seconds)),
        ]
        if llm_relay_s3_bucket
        else []
    )
    openrouter_storage_env = [
        client.V1EnvVar(
            name="LLM_SIDECAR_OPENROUTER_CAPTURE_PAYLOADS",
            value=str(openrouter_capture_payloads).lower(),
        ),
        *(
            [
                client.V1EnvVar(name="LLM_SIDECAR_LLM_RELAY_S3_BUCKET", value=llm_relay_s3_bucket),
                client.V1EnvVar(name="LLM_SIDECAR_LLM_RELAY_S3_PREFIX", value=llm_relay_s3_prefix),
            ]
            if llm_relay_s3_bucket
            else []
        ),
        *(
            [client.V1EnvVar(name="LLM_SIDECAR_LLM_DEBUG_BODY_S3_BUCKET", value=llm_debug_body_s3_bucket)]
            if llm_debug_body_s3_bucket
            else []
        ),
    ]
    openrouter_routing_env = [
        client.V1EnvVar(
            name="LLM_SIDECAR_OPENROUTER_API_KEY",
            value="" if openrouter_key_secret_name is None else None,
            value_from=(
                client.V1EnvVarSource(
                    secret_key_ref=client.V1SecretKeySelector(name=openrouter_key_secret_name, key="OPENROUTER_API_KEY")
                )
                if openrouter_key_secret_name is not None
                else None
            ),
        ),
        client.V1EnvVar(
            name="LLM_SIDECAR_OPENROUTER_MODEL_ALLOWLIST",
            value=json.dumps(openrouter_model_allowlist, separators=(",", ":")),
        ),
        *(
            [client.V1EnvVar(name="LLM_SIDECAR_OPENROUTER_ALLOWLIST_VERSION", value=openrouter_allowlist_version)]
            if openrouter_allowlist_version is not None
            else []
        ),
    ]
    return client.V1Container(
        name=LLM_SIDECAR_CONTAINER_NAME,
        image=image,
        # Run through `uv run` to use the image's workspace virtualenv, which installs
        # observatory_execution and its dependencies.
        command=["uv", "run", "--no-sync", "python", "-m", "observatory_execution.job_runner.llm_sidecar_app"],
        # Native sidecar: added to the pod's initContainers with restartPolicy=Always so it is
        # auto-terminated when the player container exits and never holds the pod open.
        restart_policy="Always",
        env_from=[
            client.V1EnvFromSource(
                config_map_ref=client.V1ConfigMapEnvSource(name="coworld-self-hosted-models", optional=True)
            )
        ],
        env=[
            client.V1EnvVar(name="LLM_SIDECAR_CONTRACT_VERSION", value=LLM_SIDECAR_CONTRACT_VERSION),
            client.V1EnvVar(name="LLM_SIDECAR_LISTEN_PORT", value=str(listen_port)),
            client.V1EnvVar(name="LLM_SIDECAR_REGION", value=region),
            # Required per-pod request ceiling protects shared provider capacity.
            client.V1EnvVar(
                name="LLM_SIDECAR_REQUEST_LIMIT_PER_MINUTE",
                value=str(request_limit_per_minute),
            ),
            client.V1EnvVar(
                name="LLM_SIDECAR_REQUEST_METADATA",
                value=serialize_llm_request_metadata(metadata),
            ),
            *(
                [client.V1EnvVar(name="LLM_SIDECAR_PLAYER_SLOT_COUNT", value=str(player_slot_count))]
                if player_slot_count is not None
                else []
            ),
            *(
                [client.V1EnvVar(name="LLM_SIDECAR_RUNTIME_DEADLINE", value=runtime_deadline)]
                if runtime_deadline is not None
                else []
            ),
            *sink_tuning_env,
            *openrouter_storage_env,
            *openrouter_routing_env,
            *(egress_relay_client_env(egress_relay_url, prefix="LLM_SIDECAR") if egress_relay_url else []),
            *(
                [
                    client.V1EnvVar(
                        name="LLM_SIDECAR_CHECKPOINT_ROUTES",
                        value_from=client.V1EnvVarSource(
                            secret_key_ref=client.V1SecretKeySelector(
                                name=checkpoint_routes_secret_name, key="routes.json"
                            )
                        ),
                    )
                ]
                if checkpoint_routes_secret_name is not None
                else []
            ),
            client.V1EnvVar(
                name="POD_NAME",
                value_from=client.V1EnvVarSource(field_ref=client.V1ObjectFieldSelector(field_path="metadata.name")),
            ),
            # League-configured per-episode per-player-pod LLM spend ceiling (estimated USD),
            # enforced by the sidecar. Absent means no limit.
            *(
                [client.V1EnvVar(name="LLM_SIDECAR_SPEND_LIMIT_USD", value=spend_limit_usd)]
                if spend_limit_usd is not None
                else []
            ),
            # Self-provide the full IRSA web-identity env (see the app_backend mirror): botocore's
            # default credential chain needs BOTH AWS_ROLE_ARN and AWS_WEB_IDENTITY_TOKEN_FILE to
            # assume the role from the projected token, and the EKS webhook can't be relied on for
            # an initContainer / skip-listed container.
            *(
                [
                    client.V1EnvVar(name="AWS_ENDPOINT_URL_S3", value=local_artifact_endpoint_url),
                    client.V1EnvVar(name="AWS_ACCESS_KEY_ID", value=local_artifact_access_key_id),
                    client.V1EnvVar(name="AWS_SECRET_ACCESS_KEY", value=local_artifact_secret_access_key),
                ]
                if local_artifacts
                else [
                    client.V1EnvVar(name="AWS_ROLE_ARN", value=role_arn),
                    client.V1EnvVar(name="AWS_WEB_IDENTITY_TOKEN_FILE", value=LLM_SIDECAR_TOKEN_FILE),
                ]
            ),
        ],
        ports=[client.V1ContainerPort(container_port=listen_port, name="llm")],
        # Exec probe, not httpGet: the sidecar binds 127.0.0.1, unreachable via the pod IP.
        startup_probe=client.V1Probe(
            _exec=client.V1ExecAction(command=_healthz_probe_command(listen_port)),
            period_seconds=1,
            failure_threshold=30,
        ),
        readiness_probe=client.V1Probe(
            _exec=client.V1ExecAction(command=_healthz_probe_command(listen_port)),
            timeout_seconds=3,
            period_seconds=5,
            failure_threshold=3,
        ),
        resources=client.V1ResourceRequirements(requests={"cpu": "100m", "memory": "128Mi"}),
        volume_mounts=[
            client.V1VolumeMount(
                name=LLM_SIDECAR_TOKEN_VOLUME_NAME,
                mount_path=LLM_SIDECAR_TOKEN_MOUNT_PATH,
                read_only=True,
            ),
            *(
                [
                    client.V1VolumeMount(
                        name=EGRESS_RELAY_CLIENT_TLS_VOLUME_NAME,
                        mount_path=EGRESS_RELAY_CLIENT_TLS_MOUNT_PATH,
                        read_only=True,
                    )
                ]
                if egress_relay_url
                else []
            ),
        ],
    )


def _healthz_probe_command(listen_port: int) -> list[str]:
    # Runs inside the sidecar container, so 127.0.0.1 reaches the loopback-bound listener.
    return [
        "python",
        "-c",
        "import urllib.request; "
        f"urllib.request.urlopen('http://127.0.0.1:{listen_port}{LLM_SIDECAR_HEALTH_PATH}', timeout=2)",
    ]


def llm_app_endpoint_env(listen_port: int) -> list[client.V1EnvVar]:
    """Native SDK endpoints; only the sidecar holds the provider credential."""
    endpoint = f"http://127.0.0.1:{listen_port}"
    return [
        client.V1EnvVar(name="COWORLD_LLM_ENABLED", value="true"),
        client.V1EnvVar(name="COWORLD_LLM_ENDPOINT", value=endpoint),
        client.V1EnvVar(name="ANTHROPIC_BASE_URL", value=endpoint),
        client.V1EnvVar(name="ANTHROPIC_API_KEY", value="sidecar"),
        client.V1EnvVar(name="ANTHROPIC_AUTH_TOKEN", value="sidecar"),
        client.V1EnvVar(name="OPENAI_BASE_URL", value=f"{endpoint}/v1"),
        client.V1EnvVar(name="OPENAI_API_KEY", value="sidecar"),
    ]


def llm_sidecar_token_volume(
    *,
    audience: str = "sts.amazonaws.com",
    expiration_seconds: int = 3600,
) -> client.V1Volume:
    """Projected identity for sidecar event/body S3 storage, never caller inference."""
    return client.V1Volume(
        name=LLM_SIDECAR_TOKEN_VOLUME_NAME,
        projected=client.V1ProjectedVolumeSource(
            sources=[
                client.V1VolumeProjection(
                    service_account_token=client.V1ServiceAccountTokenProjection(
                        audience=audience,
                        expiration_seconds=expiration_seconds,
                        path=LLM_SIDECAR_TOKEN_PATH,
                    )
                )
            ]
        ),
    )


def egress_relay_client_tls_volume() -> client.V1Volume:
    return client.V1Volume(
        name=EGRESS_RELAY_CLIENT_TLS_VOLUME_NAME,
        secret=client.V1SecretVolumeSource(secret_name=EGRESS_RELAY_CLIENT_TLS_SECRET_NAME),
    )
