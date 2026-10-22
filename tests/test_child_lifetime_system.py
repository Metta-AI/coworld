"""Exercise child cleanup through hosted episodes on an isolated local stack.

METTA_COWORLD_CHILD_LIFETIME_SYSTEM_CONFIG supplies server, Kubernetes context,
namespace, Coworld ID, and a two-seat Paint Arena policy reference. The Coworld
needs short (successful) and long (exceeding its deadline) variants. The policy
must keep running after its game connection closes so cleanup is observable.
The fault case requires a local kind cluster and Docker access to its node.
"""

import json
import os
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import httpx
import pytest
from kubernetes import client, config
from pydantic import BaseModel

from coworld.api_client import CoworldApiClient
from softmax.auth import load_current_token


class ChildLifetimeProof(BaseModel):
    server: str
    context: str
    namespace: str
    coworld_id: str
    policy_ref: str


@pytest.mark.parametrize("ending", ["success", "cancel", "coordinator_killed"])
def test_hosted_children_stop_with_their_episode(tmp_path: Path, ending: str) -> None:
    configured = os.environ.get("METTA_COWORLD_CHILD_LIFETIME_SYSTEM_CONFIG")
    if not configured:
        pytest.skip("Requires an isolated local hosted stack and a lingering Paint Arena player")
    proof = ChildLifetimeProof.model_validate_json(Path(configured).read_bytes())
    assert urlparse(proof.server).hostname in {"localhost", "127.0.0.1"}
    assert proof.context.startswith("kind-")
    assert proof.namespace.startswith("jobs-")
    token = load_current_token(server=proof.server)
    assert token is not None
    assert token.startswith("debug:local-dev:"), "Requires local debug auth, never a production proxy token"
    case_id = uuid4().hex
    with (
        CoworldApiClient.from_login(server_url=proof.server) as api,
        config.new_client_from_config(context=proof.context) as cluster,
        httpx.Client(
            base_url=f"{proof.server}/observatory",
            headers={"Authorization": f"Bearer {token}"},
            timeout=60,
        ) as http,
    ):
        core = client.CoreV1Api(cluster)
        batch = api.create_experience_request(
            {
                "idempotency_key": f"child-lifetime-{case_id}",
                "private": True,
                "coworld_id": proof.coworld_id,
                "variant_id": "short" if ending == "success" else "long",
                "roster": [{"player": {"policy_ref": proof.policy_ref}, "slot": slot} for slot in range(2)],
                "num_episodes": 1,
            }
        )
        (tmp_path / "batch.json").write_text(batch.model_dump_json())
        assert len(batch.episodes) == 1
        try:
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                episode = api.get_episode_request(batch.episodes[0].id)
                if episode.job_id is not None:
                    pods = core.list_namespaced_pod(proof.namespace, label_selector=f"job-id={episode.job_id}").items
                    parents = [pod for pod in pods if pod.metadata.labels["coworld-component"] == "game"]
                    children = [pod for pod in pods if pod.metadata.labels["coworld-component"] == "player"]
                    if (
                        len(parents) == 1
                        and len(children) == 2
                        and all(pod.status.phase == "Running" for pod in [*parents, *children])
                    ):
                        break
                time.sleep(0.5)
            else:
                pytest.fail("The hosted episode never started its game and two players")
            parent = parents[0]
            (tmp_path / "started-pods.json").write_text(json.dumps(cluster.sanitize_for_serialization(pods)))
            lifetime = parent.spec.active_deadline_seconds
            assert lifetime is not None and 0 < lifetime <= 600
            for child in children:
                assert child.spec.active_deadline_seconds == lifetime
                assert child.spec.restart_policy == "Never"
                assert any(owner.uid == parent.metadata.uid for owner in child.metadata.owner_references)
            if ending == "coordinator_killed":
                # Simulate orphaning so garbage collection cannot mask a missing child deadline.
                for child in children:
                    core.patch_namespaced_pod(
                        child.metadata.name,
                        proof.namespace,
                        [
                            {"op": "test", "path": "/metadata/uid", "value": child.metadata.uid},
                            {"op": "remove", "path": "/metadata/ownerReferences"},
                            {"op": "add", "path": "/metadata/labels/coworld-test-lifetime", "value": case_id},
                        ],
                    )
                worker = next(status for status in parent.status.container_statuses if status.name == "worker")
                assert worker.container_id.startswith("containerd://")
                # Signal from the kind node's ancestor PID namespace; in-container signals to PID 1 are restricted.
                subprocess.run(
                    [
                        "docker",
                        "exec",
                        parent.spec.node_name,
                        "ctr",
                        "-n",
                        "k8s.io",
                        "tasks",
                        "kill",
                        "--signal",
                        "SIGKILL",
                        worker.container_id.removeprefix("containerd://"),
                    ],
                    check=True,
                    timeout=30,
                )
                # Prevent infrastructure retries from launching another episode during the orphan proof.
                response = http.post(f"/v2/experience-requests/{batch.id}/cancel")
                response.raise_for_status()
            elif ending == "cancel":
                response = http.post(f"/v2/experience-requests/{batch.id}/cancel")
                response.raise_for_status()
            deadline = time.monotonic() + lifetime + 90
            while time.monotonic() < deadline:
                remaining = core.list_namespaced_pod(
                    proof.namespace, label_selector=f"job-id={episode.job_id},coworld-component=player"
                ).items
                if ending == "coordinator_killed":
                    assert {pod.metadata.uid for pod in remaining} == {pod.metadata.uid for pod in children}
                    if all(
                        pod.status.phase == "Failed" and pod.status.reason == "DeadlineExceeded" for pod in remaining
                    ):
                        break
                elif not remaining:
                    break
                time.sleep(0.5)
            else:
                pytest.fail("Player containers outlived the episode's hard lifetime and termination grace")
            (tmp_path / "remaining-pods.json").write_text(json.dumps(cluster.sanitize_for_serialization(remaining)))
            episode = api.get_episode_request(batch.episodes[0].id)
            if ending == "success":
                completion_deadline = time.monotonic() + 90
                while (
                    episode.status not in {"completed", "failed", "cancelled"}
                    and time.monotonic() < completion_deadline
                ):
                    time.sleep(0.5)
                    episode = api.get_episode_request(batch.episodes[0].id)
                assert episode.status == "completed"
                assert episode.episode_id is not None
            (tmp_path / "episode.json").write_text(episode.model_dump_json())
        finally:
            response = http.post(f"/v2/experience-requests/{batch.id}/cancel")
            # Completed and failed requests reject cancellation with 409.
            assert response.status_code in {200, 409}, response.text
            core.delete_collection_namespaced_pod(proof.namespace, label_selector=f"coworld-test-lifetime={case_id}")
            cleanup_deadline = time.monotonic() + 90
            while time.monotonic() < cleanup_deadline:
                current = api.get_episode_request(batch.episodes[0].id)
                if (
                    current.job_id is None
                    or not core.list_namespaced_pod(
                        proof.namespace, label_selector=f"job-id={current.job_id},coworld-component=player"
                    ).items
                ):
                    break
                time.sleep(0.5)
            else:
                pytest.fail("Cancelled test episode still has player pods")
