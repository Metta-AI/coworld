from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from kubernetes import client
from kubernetes.client.rest import ApiException

from coworld.runner.io import RunnerEpisodeError
from coworld.runner.self_hosted_inference import wait_for_self_hosted_models

MODEL = "self-hosted/parley-qwen35-4b"


@contextmanager
def kubernetes_api(
    *, becomes_ready: bool = True, deny_read: bool = False, replicas: int = 1
) -> Iterator[tuple[client.AppsV1Api, list]]:
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            calls.append(("GET", self.path, None))
            reads = sum(method == "GET" and path == self.path for method, path, _ in calls)
            # First a stale ready generation, then the new generation still loading.
            status = {
                "observedGeneration": 1 if reads == 1 else 2,
                "updatedReplicas": 1,
                "readyReplicas": 1 if reads == 1 or (becomes_ready and reads >= 3) else 0,
            }
            self.send_response(403 if deny_read else 200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {
                        "apiVersion": "apps/v1",
                        "kind": "Deployment",
                        "metadata": {"name": "coworld-inference", "generation": 2},
                        "spec": {
                            "replicas": replicas,
                            "selector": {"matchLabels": {"app": "inference"}},
                            "template": {"spec": {"containers": [{"name": "model", "image": "model"}]}},
                        },
                        "status": status,
                    }
                ).encode()
            )

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    configuration = client.Configuration()
    configuration.host = f"http://127.0.0.1:{server.server_port}"
    with client.ApiClient(configuration) as api_client:
        try:
            yield client.AppsV1Api(api_client), calls
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


def test_timeout_is_a_platform_failure_and_does_not_admit_the_game() -> None:
    with (
        kubernetes_api(becomes_ready=False) as (api, calls),
        pytest.raises(RunnerEpisodeError, match="did not become ready") as error,
    ):
        wait_for_self_hosted_models(
            api, "jobs", {MODEL}, {MODEL: "coworld-inference"}, timeout_seconds=0.03, poll_seconds=0.005
        )
    assert error.value.error_type == "platform_error"
    assert len(calls) > 1


def test_permission_errors_are_not_treated_as_readiness_or_retried() -> None:
    with kubernetes_api(deny_read=True) as (api, calls), pytest.raises(ApiException) as error:
        wait_for_self_hosted_models(api, "jobs", {MODEL}, {MODEL: "coworld-inference"})
    assert error.value.status == 403
    assert len(calls) == 1


def test_scaled_to_zero_fails_without_waking_deployment() -> None:
    with kubernetes_api(replicas=0) as (api, calls), pytest.raises(RunnerEpisodeError, match="scaled to zero") as error:
        wait_for_self_hosted_models(api, "jobs", {MODEL}, {MODEL: "coworld-inference"})
    assert error.value.error_type == "config_error"
    assert [method for method, _, _ in calls] == ["GET"]
