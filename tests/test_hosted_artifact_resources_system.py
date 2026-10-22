"""Exercise large artifacts through a local hosted episode and its real storage service.

METTA_COWORLD_ARTIFACT_SYSTEM_CONFIG names a JSON file with server, namespace,
coworld_id, policy_ref, and expected_artifacts (kind, size_bytes, sha256).
Use an isolated `metta dev up --full-coworld` stack and a local USER credential.
The fixture must play a complete two-seat Paint Arena game and emit the named files.
"""

import hashlib
import json
import os
import time
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import httpx
import pytest
from kubernetes import client as k8s_client
from kubernetes import config as k8s_config
from pydantic import BaseModel, Field

from coworld.api_client import CoworldApiClient
from softmax_client import credentials as softmax_credentials


class ExpectedArtifact(BaseModel):
    kind: str
    size_bytes: int
    sha256: str


class HostedArtifactProof(BaseModel):
    server: str
    namespace: str
    coworld_id: str
    policy_ref: str
    player_memory_limit: str = "80Gi"
    expected_artifacts: list[ExpectedArtifact]
    oversized_coworlds: dict[str, str] = Field(default_factory=dict)


def test_hosted_episode_preserves_large_artifacts_and_resource_requests(tmp_path: Path) -> None:
    configured = os.environ.get("METTA_COWORLD_ARTIFACT_SYSTEM_CONFIG")
    if configured is None:
        pytest.skip("Requires an isolated local hosted stack and a large-output game fixture")
    proof = HostedArtifactProof.model_validate_json(Path(configured).read_bytes())
    assert urlparse(proof.server).hostname in {"localhost", "127.0.0.1"}
    assert proof.namespace.startswith("jobs-")
    assert proof.expected_artifacts
    token = softmax_credentials.load_current_token(server=proof.server)
    assert token is not None
    request = {
        "idempotency_key": f"artifact-resources-{uuid4().hex}",
        "private": True,
        "coworld_id": proof.coworld_id,
        "variant_id": "default",
        "roster": [{"player": {"policy_ref": proof.policy_ref}, "slot": slot} for slot in range(2)],
        "num_episodes": 1,
    }
    observed: set[str] = set()
    with (
        CoworldApiClient.from_login(server_url=proof.server) as api,
        k8s_config.new_client_from_config(context="orbstack") as cluster,
    ):
        batch = api.create_experience_request(request)
        assert api.create_experience_request(request).id == batch.id
        (tmp_path / "request.json").write_text(json.dumps(request))
        (tmp_path / "batch.json").write_text(batch.model_dump_json())
        assert len(batch.episodes) == 1
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            episode = api.get_episode_request(batch.episodes[0].id)
            if episode.job_id is not None:
                pods = k8s_client.CoreV1Api(cluster).list_namespaced_pod(
                    proof.namespace, label_selector=f"job-id={episode.job_id}"
                )
                for pod in pods.items:
                    (tmp_path / f"{pod.metadata.name}.json").write_text(
                        json.dumps(cluster.sanitize_for_serialization(pod))
                    )
                    for container in pod.spec.containers + (pod.spec.init_containers or []):
                        assert container.resources.limits["memory"], container.name
                        if container.name in {"game", "worker", "player"}:
                            expected = {
                                "game": ({"cpu": "250m", "memory": "512Mi"}, "24Gi"),
                                "worker": ({"cpu": "250m", "memory": "512Mi"}, "4Gi"),
                                "player": ({"cpu": "250m", "memory": "512Mi"}, proof.player_memory_limit),
                            }
                            requests, memory = expected[container.name]
                            assert container.resources.requests == requests
                            assert container.resources.limits == {"memory": memory}
                            observed.add(container.name)
                    for volume in pod.spec.volumes or []:
                        if volume.name == "coworld-workdir":
                            assert volume.empty_dir.size_limit == "32Gi"
                            observed.add("workdir")
            if episode.status in {"completed", "failed", "canceled"}:
                break
            time.sleep(1)
        else:
            pytest.fail("Hosted episode did not finish within ten minutes")
        (tmp_path / "episode.json").write_text(episode.model_dump_json())
        assert episode.status == "completed", episode.error
        assert observed == {"game", "worker", "player", "workdir"}
        assert episode.replay_url and episode.scores
        assert len(episode.participants) == 2
        assert api.get_episode_request_artifact_bytes(episode.id, "replay")
        for artifact in proof.expected_artifacts:
            digest = hashlib.sha256()
            size = 0
            with httpx.stream(
                "GET",
                f"{proof.server}/observatory/jobs/{episode.job_id}/artifacts/{artifact.kind}",
                headers={"Authorization": f"Bearer {token}", "X-Use-Elevated-Privileges": "true"},
                timeout=120,
            ) as response:
                response.raise_for_status()
                for chunk in response.iter_bytes(chunk_size=1024 * 1024):
                    digest.update(chunk)
                    size += len(chunk)
            assert size == artifact.size_bytes
            assert digest.hexdigest() == artifact.sha256


def test_hosted_oversized_outputs_fail_without_scores(tmp_path: Path) -> None:
    configured = os.environ.get("METTA_COWORLD_ARTIFACT_SYSTEM_CONFIG")
    if configured is None:
        pytest.skip("Requires an isolated hosted stack with oversized-output game fixtures")
    proof = HostedArtifactProof.model_validate_json(Path(configured).read_bytes())
    assert urlparse(proof.server).hostname in {"localhost", "127.0.0.1"}
    assert proof.namespace.startswith("jobs-")
    if not proof.oversized_coworlds:
        pytest.skip("Requires the optional oversized-output game fixtures")
    assert set(proof.oversized_coworlds) == {"results_malformed", "game_contract_violation"}
    with CoworldApiClient.from_login(server_url=proof.server) as api:
        for error_type, coworld_id in proof.oversized_coworlds.items():
            request = {
                "idempotency_key": f"oversized-output-{uuid4().hex}",
                "private": True,
                "coworld_id": coworld_id,
                "variant_id": "default",
                "roster": [{"player": {"policy_ref": proof.policy_ref}, "slot": slot} for slot in range(2)],
                "num_episodes": 1,
            }
            batch = api.create_experience_request(request)
            deadline = time.monotonic() + 600
            while time.monotonic() < deadline:
                episode = api.get_episode_request(batch.episodes[0].id)
                if episode.status in {"completed", "failed", "canceled"}:
                    break
                time.sleep(1)
            else:
                pytest.fail("Oversized hosted episode did not terminate within ten minutes")
            (tmp_path / f"{error_type}.json").write_text(episode.model_dump_json())
            assert episode.status == "failed", episode
            assert episode.error_type == error_type, episode.error
            assert not episode.scores
