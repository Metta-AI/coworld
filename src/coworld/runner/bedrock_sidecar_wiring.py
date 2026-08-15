from __future__ import annotations

import json

from kubernetes import client

from coworld.runner.bedrock_metadata import CoworldEpisodeBedrockMetadata, serialize_bedrock_request_metadata

BEDROCK_SIDECAR_CONTAINER_NAME = "bedrock-sidecar"
BEDROCK_SIDECAR_TOKEN_VOLUME_NAME = "bedrock-sidecar-aws-token"
BEDROCK_SIDECAR_TOKEN_MOUNT_PATH = "/var/run/secrets/bedrock-sidecar"
BEDROCK_SIDECAR_TOKEN_PATH = "token"
BEDROCK_SIDECAR_TOKEN_FILE = f"{BEDROCK_SIDECAR_TOKEN_MOUNT_PATH}/{BEDROCK_SIDECAR_TOKEN_PATH}"
BEDROCK_SIDECAR_CONTRACT_VERSION = "core-v1"
BEDROCK_SIDECAR_HEALTH_PATH = f"/healthz/{BEDROCK_SIDECAR_CONTRACT_VERSION}"
BEDROCK_PROMPT_PREFIX_CONTROL_CONFIG_MAP_NAME = "bedrock-prompt-prefix-measurement"
BEDROCK_PROMPT_PREFIX_ENABLED_PATH = f"{BEDROCK_SIDECAR_TOKEN_MOUNT_PATH}/prompt-prefix-measurement-enabled"
BEDROCK_RUNTIME_ENDPOINT_TEMPLATE = "https://bedrock-runtime.{region}.amazonaws.com"

# Non-functional placeholder credentials for the app container's AWS SDK. The SDK needs creds to
# sign before it sends to the localhost sidecar, which then re-signs with the real IRSA identity
# it alone holds.
_DUMMY_APP_CREDENTIAL = "bedrock-sidecar"

# Keys the platform controls on a sidecar-backed app container; a user/policy env must never
# override them (else a saved AWS_ENDPOINT_URL_BEDROCK_RUNTIME could bypass the sidecar).
RESERVED_SIDECAR_APP_ENV = frozenset(
    {
        "AWS_ENDPOINT_URL_BEDROCK_RUNTIME",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_REGION",
        "AWS_DEFAULT_REGION",
        # Bedrock API-key (bearer) auth: reserve both so a policy's own token/file can't override
        # the placeholder; the sidecar strips the bearer header and re-signs with IRSA regardless.
        "AWS_BEARER_TOKEN_BEDROCK",
        "AWS_BEARER_TOKEN_BEDROCK_FILE",
    }
)


def resolve_image_attribution_key(image: str) -> str:
    """Coworld stays app_backend-independent: parse pinned digests, else keep the image ref."""
    digest_marker = "@sha256:"
    if digest_marker in image:
        return f"sha256:{image.split(digest_marker, maxsplit=1)[1]}"
    return image


def build_bedrock_sidecar(
    *,
    metadata: CoworldEpisodeBedrockMetadata,
    region: str,
    listen_port: int,
    upstream_endpoint: str | None,
    image: str,
    role_arn: str,
    completions_bucket: str | None,
    completions_prefix: str,
    flush_records: int,
    flush_seconds: float,
    llm_relay_s3_bucket: str | None = None,
    llm_relay_s3_prefix: str = "llm-relay",
    llm_debug_body_s3_bucket: str | None = None,
    openrouter_capture_payloads: bool = True,
    spend_limit_usd: str | None = None,
    pricing_json: str | None = None,
    prompt_prefix_sample_rate: float = 0.0,
    openrouter_key_secret_name: str | None = None,
    openrouter_model_allowlist: list[str] | None = None,
    openrouter_model_aliases: dict[str, str] | None = None,
    openrouter_allowlist_version: str | None = None,
) -> client.V1Container:
    upstream = upstream_endpoint or BEDROCK_RUNTIME_ENDPOINT_TEMPLATE.format(region=region)
    # Optional S3 sink for completion records (latency/errors); unset bucket keeps the sidecar
    # log-only. Mirrors the app_backend wiring — the sidecar proxy image is the same single source.
    completion_env = (
        [
            client.V1EnvVar(name="BEDROCK_SIDECAR_COMPLETIONS_BUCKET", value=completions_bucket),
            client.V1EnvVar(name="BEDROCK_SIDECAR_COMPLETIONS_PREFIX", value=completions_prefix),
        ]
        if completions_bucket
        else []
    )
    sink_tuning_env = (
        [
            client.V1EnvVar(name="BEDROCK_SIDECAR_FLUSH_RECORDS", value=str(flush_records)),
            client.V1EnvVar(name="BEDROCK_SIDECAR_FLUSH_SECONDS", value=str(flush_seconds)),
        ]
        if completions_bucket or llm_relay_s3_bucket
        else []
    )
    openrouter_storage_env = [
        client.V1EnvVar(
            name="BEDROCK_SIDECAR_OPENROUTER_CAPTURE_PAYLOADS",
            value=str(openrouter_capture_payloads).lower(),
        ),
        *(
            [
                client.V1EnvVar(name="BEDROCK_SIDECAR_LLM_RELAY_S3_BUCKET", value=llm_relay_s3_bucket),
                client.V1EnvVar(name="BEDROCK_SIDECAR_LLM_RELAY_S3_PREFIX", value=llm_relay_s3_prefix),
            ]
            if llm_relay_s3_bucket
            else []
        ),
        *(
            [client.V1EnvVar(name="BEDROCK_SIDECAR_LLM_DEBUG_BODY_S3_BUCKET", value=llm_debug_body_s3_bucket)]
            if llm_debug_body_s3_bucket
            else []
        ),
    ]
    prompt_prefix_measurement_env = (
        [
            client.V1EnvVar(
                name="BEDROCK_SIDECAR_PROMPT_PREFIX_SAMPLE_RATE",
                value=str(prompt_prefix_sample_rate),
            ),
            client.V1EnvVar(
                name="BEDROCK_SIDECAR_PROMPT_PREFIX_ENABLED_PATH",
                value=BEDROCK_PROMPT_PREFIX_ENABLED_PATH,
            ),
        ]
        if prompt_prefix_sample_rate > 0
        else []
    )
    openrouter_routing_env = (
        [
            client.V1EnvVar(name="BEDROCK_SIDECAR_LLM_PROVIDER", value="openrouter"),
            client.V1EnvVar(
                name="BEDROCK_SIDECAR_OPENROUTER_API_KEY",
                value_from=client.V1EnvVarSource(
                    secret_key_ref=client.V1SecretKeySelector(
                        name=openrouter_key_secret_name,
                        key="OPENROUTER_API_KEY",
                    )
                ),
            ),
            client.V1EnvVar(
                name="BEDROCK_SIDECAR_OPENROUTER_MODEL_ALLOWLIST",
                value=json.dumps(openrouter_model_allowlist, separators=(",", ":")),
            ),
            client.V1EnvVar(
                name="BEDROCK_SIDECAR_OPENROUTER_MODEL_ALIASES",
                value=json.dumps(openrouter_model_aliases, separators=(",", ":")),
            ),
            client.V1EnvVar(
                name="BEDROCK_SIDECAR_OPENROUTER_ALLOWLIST_VERSION",
                value=openrouter_allowlist_version,
            ),
        ]
        if openrouter_key_secret_name is not None
        else []
    )
    return client.V1Container(
        name=BEDROCK_SIDECAR_CONTAINER_NAME,
        image=image,
        # Run through `uv run` to use the image's workspace virtualenv (see the app_backend
        # mirror): the sidecar image installs metta.app_backend into a uv venv, so a bare
        # `python` can't import it (ModuleNotFoundError -> crash loop).
        command=["uv", "run", "--no-sync", "python", "-m", "metta.app_backend.job_runner.bedrock_sidecar"],
        # Native sidecar: added to the pod's initContainers with restartPolicy=Always so it is
        # auto-terminated when the player container exits and never holds the pod open.
        restart_policy="Always",
        env=[
            client.V1EnvVar(name="BEDROCK_SIDECAR_CONTRACT_VERSION", value=BEDROCK_SIDECAR_CONTRACT_VERSION),
            client.V1EnvVar(name="BEDROCK_SIDECAR_LISTEN_PORT", value=str(listen_port)),
            client.V1EnvVar(name="BEDROCK_SIDECAR_REGION", value=region),
            client.V1EnvVar(name="BEDROCK_SIDECAR_UPSTREAM_ENDPOINT", value=upstream),
            client.V1EnvVar(
                name="BEDROCK_SIDECAR_REQUEST_METADATA",
                value=serialize_bedrock_request_metadata(metadata),
            ),
            *completion_env,
            *sink_tuning_env,
            *openrouter_storage_env,
            *prompt_prefix_measurement_env,
            *openrouter_routing_env,
            client.V1EnvVar(
                name="POD_NAME",
                value_from=client.V1EnvVarSource(field_ref=client.V1ObjectFieldSelector(field_path="metadata.name")),
            ),
            # League-configured per-episode per-player-pod LLM spend ceiling (estimated USD),
            # enforced by the sidecar. Absent means no limit.
            *(
                [client.V1EnvVar(name="BEDROCK_SIDECAR_SPEND_LIMIT_USD", value=spend_limit_usd)]
                if spend_limit_usd is not None
                else []
            ),
            # Per-model USD rates snapshotted from the server's DB-backed pricing at dispatch
            # (forwarded by the dispatcher), so in-pod spend metering matches server-side
            # reporting. Absent means the sidecar falls back to family estimates.
            *(
                [client.V1EnvVar(name="BEDROCK_SIDECAR_PRICING_JSON", value=pricing_json)]
                if pricing_json is not None
                else []
            ),
            # Self-provide the full IRSA web-identity env (see the app_backend mirror): botocore's
            # default credential chain needs BOTH AWS_ROLE_ARN and AWS_WEB_IDENTITY_TOKEN_FILE to
            # assume the role from the projected token, and the EKS webhook can't be relied on for
            # an initContainer / skip-listed container.
            client.V1EnvVar(name="AWS_ROLE_ARN", value=role_arn),
            client.V1EnvVar(name="AWS_WEB_IDENTITY_TOKEN_FILE", value=BEDROCK_SIDECAR_TOKEN_FILE),
        ],
        ports=[client.V1ContainerPort(container_port=listen_port, name="bedrock")],
        # Exec probe, not httpGet: the sidecar binds 127.0.0.1, unreachable via the pod IP.
        readiness_probe=client.V1Probe(
            _exec=client.V1ExecAction(command=_healthz_probe_command(listen_port)),
            period_seconds=1,
            failure_threshold=3,
        ),
        resources=client.V1ResourceRequirements(requests={"cpu": "100m", "memory": "128Mi"}),
        volume_mounts=[
            client.V1VolumeMount(
                name=BEDROCK_SIDECAR_TOKEN_VOLUME_NAME,
                mount_path=BEDROCK_SIDECAR_TOKEN_MOUNT_PATH,
                read_only=True,
            )
        ],
    )


def _healthz_probe_command(listen_port: int) -> list[str]:
    # Runs inside the sidecar container, so 127.0.0.1 reaches the loopback-bound listener.
    return [
        "python",
        "-c",
        "import urllib.request; "
        f"urllib.request.urlopen('http://127.0.0.1:{listen_port}{BEDROCK_SIDECAR_HEALTH_PATH}', timeout=2)",
    ]


def bedrock_app_endpoint_env(listen_port: int, region: str) -> list[client.V1EnvVar]:
    """App-container env to reach Bedrock only via the localhost sidecar.

    Includes placeholder credentials + region (the AWS SDK needs both to build/sign a request)
    and a placeholder Bedrock API key (so bearer-token apps pass their "token configured?"
    precondition and actually call). All non-functional — the sidecar strips the client auth
    header (SigV4 or Bearer) and re-signs with the real identity.
    """
    return [
        client.V1EnvVar(name="AWS_ENDPOINT_URL_BEDROCK_RUNTIME", value=f"http://127.0.0.1:{listen_port}"),
        client.V1EnvVar(name="AWS_ACCESS_KEY_ID", value=_DUMMY_APP_CREDENTIAL),
        client.V1EnvVar(name="AWS_SECRET_ACCESS_KEY", value=_DUMMY_APP_CREDENTIAL),
        client.V1EnvVar(name="AWS_BEARER_TOKEN_BEDROCK", value=_DUMMY_APP_CREDENTIAL),
        client.V1EnvVar(name="AWS_REGION", value=region),
        client.V1EnvVar(name="AWS_DEFAULT_REGION", value=region),
    ]


def bedrock_sidecar_token_volume(
    *,
    audience: str = "sts.amazonaws.com",
    expiration_seconds: int = 3600,
    prompt_prefix_measurement: bool = False,
) -> client.V1Volume:
    return client.V1Volume(
        name=BEDROCK_SIDECAR_TOKEN_VOLUME_NAME,
        projected=client.V1ProjectedVolumeSource(
            sources=[
                client.V1VolumeProjection(
                    service_account_token=client.V1ServiceAccountTokenProjection(
                        audience=audience,
                        expiration_seconds=expiration_seconds,
                        path=BEDROCK_SIDECAR_TOKEN_PATH,
                    )
                ),
                *(
                    [
                        client.V1VolumeProjection(
                            config_map=client.V1ConfigMapProjection(
                                name=BEDROCK_PROMPT_PREFIX_CONTROL_CONFIG_MAP_NAME,
                                items=[
                                    client.V1KeyToPath(
                                        key="enabled",
                                        path="prompt-prefix-measurement-enabled",
                                    )
                                ],
                            )
                        )
                    ]
                    if prompt_prefix_measurement
                    else []
                ),
            ]
        ),
    )
