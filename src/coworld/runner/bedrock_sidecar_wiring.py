from __future__ import annotations

from kubernetes import client
from pydantic import BaseModel, ConfigDict

BEDROCK_SIDECAR_CONTAINER_NAME = "bedrock-sidecar"
BEDROCK_SIDECAR_TOKEN_VOLUME_NAME = "bedrock-sidecar-aws-token"
BEDROCK_SIDECAR_TOKEN_MOUNT_PATH = "/var/run/secrets/bedrock-sidecar"
BEDROCK_SIDECAR_TOKEN_PATH = "token"
BEDROCK_SIDECAR_TOKEN_FILE = f"{BEDROCK_SIDECAR_TOKEN_MOUNT_PATH}/{BEDROCK_SIDECAR_TOKEN_PATH}"
BEDROCK_RUNTIME_ENDPOINT_TEMPLATE = "https://bedrock-runtime.{region}.amazonaws.com"

# Non-functional placeholder credentials for the app container's AWS SDK; see the app_backend
# mirror (bedrock_sidecar_wiring.py) for the rationale. The SDK needs creds to sign before it
# sends to the localhost sidecar, which then re-signs with the real IRSA identity it alone holds.
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
    }
)


class BedrockSidecarAttribution(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    image_digest: str
    episode_request_id: str
    role: str
    slot: str


def resolve_image_attribution_key(image: str) -> str:
    """Coworld stays app_backend-independent: parse pinned digests, else keep the image ref."""
    digest_marker = "@sha256:"
    if digest_marker in image:
        return f"sha256:{image.split(digest_marker, maxsplit=1)[1]}"
    return image


def build_bedrock_sidecar(
    *,
    attribution: BedrockSidecarAttribution,
    region: str,
    listen_port: int,
    upstream_endpoint: str | None,
    image: str,
) -> client.V1Container:
    upstream = upstream_endpoint or BEDROCK_RUNTIME_ENDPOINT_TEMPLATE.format(region=region)
    return client.V1Container(
        name=BEDROCK_SIDECAR_CONTAINER_NAME,
        image=image,
        command=["python", "-m", "metta.app_backend.job_runner.bedrock_sidecar"],
        # Native sidecar: added to the pod's initContainers with restartPolicy=Always so it is
        # auto-terminated when the player container exits and never holds the pod open.
        restart_policy="Always",
        env=[
            client.V1EnvVar(name="BEDROCK_SIDECAR_LISTEN_PORT", value=str(listen_port)),
            client.V1EnvVar(name="BEDROCK_SIDECAR_REGION", value=region),
            client.V1EnvVar(name="BEDROCK_SIDECAR_UPSTREAM_ENDPOINT", value=upstream),
            client.V1EnvVar(name="BEDROCK_SIDECAR_IMAGE_DIGEST", value=attribution.image_digest),
            client.V1EnvVar(name="BEDROCK_SIDECAR_EPISODE_REQUEST_ID", value=attribution.episode_request_id),
            client.V1EnvVar(name="BEDROCK_SIDECAR_ROLE", value=attribution.role),
            client.V1EnvVar(name="BEDROCK_SIDECAR_SLOT", value=attribution.slot),
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
        f"import urllib.request; urllib.request.urlopen('http://127.0.0.1:{listen_port}/healthz', timeout=2)",
    ]


def bedrock_app_endpoint_env(listen_port: int, region: str) -> list[client.V1EnvVar]:
    """App-container env to reach Bedrock only via the localhost sidecar.

    Includes placeholder credentials + region: the AWS SDK needs both to build/sign a request
    before sending. They are non-functional (the sidecar re-signs with the real identity).
    """
    return [
        client.V1EnvVar(name="AWS_ENDPOINT_URL_BEDROCK_RUNTIME", value=f"http://127.0.0.1:{listen_port}"),
        client.V1EnvVar(name="AWS_ACCESS_KEY_ID", value=_DUMMY_APP_CREDENTIAL),
        client.V1EnvVar(name="AWS_SECRET_ACCESS_KEY", value=_DUMMY_APP_CREDENTIAL),
        client.V1EnvVar(name="AWS_REGION", value=region),
        client.V1EnvVar(name="AWS_DEFAULT_REGION", value=region),
    ]


def bedrock_sidecar_token_volume(
    *,
    audience: str = "sts.amazonaws.com",
    expiration_seconds: int = 3600,
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
                )
            ]
        ),
    )
