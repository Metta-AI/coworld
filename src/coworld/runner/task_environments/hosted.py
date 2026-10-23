"""Episode-native task control sidecar. Only this process holds cluster authority."""

import asyncio
import os
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit

import uvicorn
from kubernetes import client

from coworld.runner.bootstrap import COORDINATOR_SPEC_PATH
from coworld.runner.game_egress_proxy import _handle
from coworld.runner.kubernetes_runner import _load_incluster_config
from coworld.runner.relay_client import egress_relay_ssl_context
from coworld.runner.task_environments.kubernetes import API_TIMEOUT, TaskPods
from coworld.runner.task_environments.service import TaskControl
from coworld.types import CoworldEpisodeJobSpec

TASK_PORT = 8093
EVIDENCE_DIR = Path("/var/run/coworld-tasks")


@asynccontextmanager
async def stream_proxy(api: client.ApiClient):
    """Bridge the Kubernetes WebSocket client's HTTP proxy to the mTLS relay."""
    relay = urlsplit(os.environ["COWORLD_EGRESS_RELAY_URL"])
    relay_host, relay_port = relay.hostname, relay.port
    assert relay.scheme == "https" and relay_host and relay_port
    tls = egress_relay_ssl_context(
        ca_file=os.environ["COWORLD_EGRESS_RELAY_CA_FILE"],
        cert_file=os.environ["COWORLD_EGRESS_RELAY_CLIENT_CERT_FILE"],
        key_file=os.environ["COWORLD_EGRESS_RELAY_CLIENT_KEY_FILE"],
    )
    limit = asyncio.Semaphore(2)
    connections: set[asyncio.Task] = set()
    async with asyncio.TaskGroup() as group:

        def connected(reader, writer):
            task = group.create_task(
                _handle(
                    reader,
                    writer,
                    relay_host=relay_host,
                    relay_port=relay_port,
                    allowed_targets=frozenset({"kubernetes.default.svc:443"}),
                    tls_context=tls,
                    connection_limit=limit,
                )
            )
            connections.add(task)
            task.add_done_callback(connections.discard)

        server = await asyncio.start_server(connected, "127.0.0.1", 0)
        async with server:
            api.configuration.proxy = f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}"
            try:
                yield
            finally:
                server.close()
                for task in connections:
                    task.cancel()


async def run() -> None:
    job = CoworldEpisodeJobSpec.model_validate_json(COORDINATOR_SPEC_PATH.read_bytes())
    with (
        _load_incluster_config(
            egress_enforcement_enabled=os.environ.get("COWORLD_EGRESS_ENFORCEMENT_ENABLED") == "true"
        ) as api,
        _load_incluster_config(
            egress_enforcement_enabled=os.environ.get("COWORLD_EGRESS_ENFORCEMENT_ENABLED") == "true"
        ) as task_api,
    ):
        core = client.CoreV1Api(api)
        namespace, owner = os.environ["JOB_NAMESPACE"], os.environ["POD_NAME"]
        pod = await asyncio.to_thread(core.read_namespaced_pod, owner, namespace, _request_timeout=API_TIMEOUT)
        pods = TaskPods(
            task_api,
            namespace=namespace,
            owner_name=owner,
            owner_uid=os.environ["POD_UID"],
            expires_at=pod.status.start_time + timedelta(seconds=pod.spec.active_deadline_seconds),
            definitions=job.manifest.game.task_environments,
            evidence_dir=EVIDENCE_DIR / "evidence",
            guard_image=os.environ["COWORLD_COORDINATOR_IMAGE"],
            owner_labels={
                key: value
                for key, value in pod.metadata.labels.items()
                if key in {"job-id", "softmax.com/job-id", "coworld-id", "league-id", "coworld-source"}
            },
            node_selector=pod.spec.node_selector,
            tolerations=pod.spec.tolerations,
        )
        server = uvicorn.Server(
            uvicorn.Config(
                TaskControl(pods, os.environ["COWORLD_TASK_TOKEN"]),
                host="127.0.0.1",
                port=TASK_PORT,
                limit_concurrency=8,
                timeout_keep_alive=2,
                timeout_graceful_shutdown=30,
            )
        )

        async def watch_game() -> None:
            while not server.should_exit:
                current = await asyncio.to_thread(
                    core.read_namespaced_pod, owner, namespace, _request_timeout=API_TIMEOUT
                )
                if any(
                    status.name in {"game", "worker"} and status.state.terminated is not None
                    for status in current.status.container_statuses or []
                ):
                    await asyncio.to_thread(pods.close_all)
                    return
                await asyncio.sleep(1)

        async with AsyncExitStack() as stack:
            if os.environ.get("COWORLD_EGRESS_ENFORCEMENT_ENABLED") == "true":
                await stack.enter_async_context(stream_proxy(task_api))
            try:
                async with asyncio.TaskGroup() as group:
                    watcher = group.create_task(watch_game())
                    await server.serve()
                    watcher.cancel()
            finally:
                await asyncio.to_thread(pods.close_all)


if __name__ == "__main__":
    asyncio.run(run())
