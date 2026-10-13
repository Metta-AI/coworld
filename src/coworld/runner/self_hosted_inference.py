from __future__ import annotations

import logging
import time
from collections.abc import Iterable, Mapping
from typing import cast

from kubernetes import client

from coworld.runner.external_llm import EXTERNAL_LLM_SECRET_KEY, ExternalLlmRoute
from coworld.runner.io import RunnerEpisodeError
from coworld.runner.llm_enablement import resolve_player_llm

logger = logging.getLogger(__name__)
SELF_HOSTED_READINESS_TIMEOUT_SECONDS = 20 * 60


def requested_self_hosted_models(policy_environments: Iterable[Mapping[str, str]]) -> set[str]:
    models = set()
    for environment in policy_environments:
        llm = resolve_player_llm(environment)
        if EXTERNAL_LLM_SECRET_KEY in environment:
            route = ExternalLlmRoute.model_validate_json(environment[EXTERNAL_LLM_SECRET_KEY])
            if not llm.enabled or llm.model != route.model_id:
                raise RunnerEpisodeError(
                    "External LLM registration requires enabled inference and its exact registered model ID",
                    error_type="config_error",
                )
            # Registered contributor endpoints do not have a cluster Deployment to wait for.
            continue
        if llm.enabled and llm.model and llm.model.startswith("self-hosted/"):
            models.add(llm.model)
    return models


def wait_for_self_hosted_models(
    api: client.AppsV1Api,
    namespace: str,
    models: set[str],
    deployments: Mapping[str, str],
    *,
    timeout_seconds: float = SELF_HOSTED_READINESS_TIMEOUT_SECONDS,
    poll_seconds: float = 5,
) -> None:
    unknown = models - deployments.keys()
    if unknown:
        raise RunnerEpisodeError(
            f"Self-hosted models are not enabled for this cluster: {', '.join(sorted(unknown))}",
            error_type="config_error",
        )
    pending = {deployments[model] for model in models}
    deadline = time.monotonic() + timeout_seconds
    while pending:
        for name in sorted(pending):
            deployment = cast(
                client.V1Deployment, api.read_namespaced_deployment(name, namespace, _request_timeout=(5, 15))
            )
            status = cast(client.V1DeploymentStatus, deployment.status)
            metadata = cast(client.V1ObjectMeta, deployment.metadata)
            spec = cast(client.V1DeploymentSpec, deployment.spec)
            if spec.replicas == 0:
                raise RunnerEpisodeError(
                    f"Self-hosted inference deployment {namespace}/{name} is scaled to zero; "
                    "enable it before launching games",
                    error_type="config_error",
                )
            if (
                status.observed_generation == metadata.generation
                and status.updated_replicas == spec.replicas
                and status.ready_replicas == spec.replicas
            ):
                logger.info("Self-hosted inference deployment %s/%s is ready", namespace, name)
                pending.remove(name)
        if not pending:
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RunnerEpisodeError(
                f"Self-hosted inference did not become ready within {timeout_seconds:g}s: {', '.join(sorted(pending))}",
                error_type="platform_error",
            )
        time.sleep(min(poll_seconds, remaining))
