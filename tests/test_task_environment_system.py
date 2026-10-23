"""Real control API and Kubernetes task lifecycle; opt in with a local kind config."""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import yaml
from kubernetes import client, config
from kubernetes.stream import stream

from coworld.task_environment import CreateTask, ExecuteTask, NetworkPhase, TaskEnvironmentClient

pytestmark = pytest.mark.skipif(
    "METTA_COWORLD_TASK_SYSTEM_CONFIG" not in os.environ,
    reason="requires an explicit local kind cluster and preloaded task image",
)


@pytest.fixture(params=[False])
def control(tmp_path: Path, request: pytest.FixtureRequest):
    settings = json.loads(Path(os.environ["METTA_COWORLD_TASK_SYSTEM_CONFIG"]).read_text())
    coding = request.param == "coding"
    public = request.param is True
    assert settings["context"].startswith("kind-")
    namespace = f"task-proof-{uuid.uuid4().hex[:12]}"
    api = config.new_client_from_config(config_file=settings["kubeconfig"], context=settings["context"])
    request.addfinalizer(api.close)
    core = client.CoreV1Api(api)
    core.create_namespace(client.V1Namespace(metadata=client.V1ObjectMeta(name=namespace)))
    request.addfinalizer(lambda: core.delete_namespace(namespace))
    if coding:
        resources = list(yaml.safe_load_all(Path(settings["coding_resources"]).read_text()))
        priority = next(row for row in resources if row["kind"] == "PriorityClass")
        scheduling = client.SchedulingV1Api(api)
        created = scheduling.create_priority_class(priority)
        request.addfinalizer(
            lambda: scheduling.delete_priority_class(
                created.metadata.name,
                body=client.V1DeleteOptions(preconditions=client.V1Preconditions(uid=created.metadata.uid)),
            )
        )
        quota = next(row for row in resources if row["kind"] == "ResourceQuota")
        quota["metadata"]["namespace"] = namespace
        core.create_namespaced_resource_quota(namespace, quota)
    until = time.monotonic() + 30
    while not core.list_namespaced_service_account(namespace, field_selector="metadata.name=default").items:
        assert time.monotonic() < until, "namespace service account was not provisioned"
        time.sleep(0.2)
    owner = core.create_namespaced_pod(
        namespace,
        client.V1Pod(
            metadata=client.V1ObjectMeta(name="coordinator"),
            spec=client.V1PodSpec(
                restart_policy="Never",
                active_deadline_seconds=180,
                automount_service_account_token=False,
                containers=[
                    client.V1Container(
                        name="owner",
                        image=settings["image"],
                        image_pull_policy="IfNotPresent",
                        command=["/bin/sh", "-c", "exec sleep infinity"],
                        resources=client.V1ResourceRequirements(
                            requests={"cpu": "100m", "memory": "64Mi"},
                            limits={"cpu": "100m", "memory": "64Mi"},
                        ),
                    )
                ],
            ),
        ),
    )
    token = secrets.token_urlsafe(32)
    token_path = tmp_path / "token"
    token_path.write_text(token)
    token_path.chmod(0o600)
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "kubeconfig": settings["kubeconfig"],
                "context": settings["context"],
                "namespace": namespace,
                "owner_name": "coordinator",
                "owner_uid": owner.metadata.uid,
                "expires_at": (datetime.now(UTC) + timedelta(seconds=60)).isoformat(),
                "guard_image": settings["guard_image"],
                "definitions": {
                    "native": {
                        "isolation": "coding" if coding else "general",
                        "network": "public" if public else "no-network",
                        "network_transitions": ["no-network", "public"] if public else [],
                        "image": settings["image"],
                        "cpu_millis": 100,
                        "memory_mib": 1024 if coding else 128,
                        "storage_mib": 1024,
                        "max_instances": 3 if request.param == "serial" else 2,
                        "max_concurrent_instances": 1 if request.param == "serial" else 2,
                    },
                    "unavailable": {
                        "image": "localhost:1/unavailable@sha256:" + "0" * 64,
                        "cpu_millis": 100,
                        "memory_mib": 128,
                        "storage_mib": 1024,
                        "max_instances": 1,
                        "startup_timeout_seconds": 1,
                    },
                },
                "evidence_dir": str(tmp_path / "evidence"),
                "token_file": str(token_path),
                "port": settings["port"],
            }
        )
    )
    log = tmp_path / "control.log"
    with log.open("w") as output:
        process = subprocess.Popen(
            [sys.executable, "-m", "coworld.runner.task_environments", str(config_path)],
            stdout=output,
            stderr=subprocess.STDOUT,
        )
    try:
        until = time.monotonic() + 20
        while "Application startup complete" not in log.read_text():
            assert process.poll() is None, log.read_text()
            assert time.monotonic() < until, log.read_text()
            time.sleep(0.1)
        with httpx.Client(
            base_url=f"http://127.0.0.1:{settings['port']}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=40,
        ) as http:
            yield http, process, core, namespace
    finally:
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=30)


def run(http: httpx.Client, key: str, command: str, timeout: float = 20, output_limit: int = 65536):
    response = http.post(
        f"/tasks/{key}/exec",
        json={
            "command": ["/bin/sh", "-c", command],
            "timeout_seconds": timeout,
            "max_output_bytes": output_limit,
        },
    )
    response.raise_for_status()
    return response.json()


def test_fresh_environment_and_cleanup(control):
    http, process, core, namespace = control
    assert (
        http.post(
            "/tasks", json={"definition": "native", "key": "agent"}, headers={"Authorization": "Bearer wrong"}
        ).status_code
        == 401
    )
    for key in ("phase/agent", ".", "..", "has space", "query?", "fragment#"):
        assert http.post("/tasks", json={"definition": "native", "key": key}).status_code == 422
    request = {"definition": "native", "key": "agent"}
    first = http.post("/tasks", json=request)
    first.raise_for_status()
    assert http.post("/tasks", json=request).json() == first.json()
    assert run(http, "agent", "echo agent > /tmp/agent-sentinel; echo ready")["stdout"] == "ready\n"
    assert http.delete("/tasks/agent").status_code == 200
    assert http.post("/tasks", json=request).json() == {"kind": "task_closed"}
    fresh = http.post("/tasks", json={"definition": "native", "key": "verifier"})
    fresh.raise_for_status()
    assert fresh.json()["pod_name"] != first.json()["pod_name"]
    assert run(http, "verifier", "test ! -e /tmp/agent-sentinel; echo $?")["stdout"] == "0\n"
    assert http.post("/tasks", json={"definition": "native", "key": "third"}).json() == {
        "kind": "instance_budget_exhausted",
    }
    assert run(http, "verifier", "yes flood", output_limit=1024)["kind"] == "output_limit"
    assert run(http, "verifier", "echo cannot-reuse")["kind"] == "closed"


@pytest.mark.parametrize("control", ["serial"], indirect=True)
def test_fresh_serial_tasks_preserve_creation_and_concurrency_limits(control):
    http, process, core, namespace = control
    pod_names = set()
    for index in range(3):
        key = f"problem-{index}"
        response = http.post("/tasks", json={"definition": "native", "key": key})
        response.raise_for_status()
        pod_names.add(response.json()["pod_name"])
        assert run(http, key, "test ! -e /tmp/solution && echo clean; echo code > /tmp/solution")["stdout"] == "clean\n"
        if index < 2:
            assert http.post("/tasks", json={"definition": "native", "key": "overlap"}).json() == {
                "kind": "concurrency_budget_exhausted",
            }
        assert http.delete(f"/tasks/{key}").status_code == 200
        assert http.post("/tasks", json={"definition": "native", "key": key}).json() == {"kind": "task_closed"}
        until = time.monotonic() + 20
        while core.list_namespaced_pod(namespace, label_selector="coworld-component=task").items:
            assert time.monotonic() < until, "closed task pod was not removed"
            time.sleep(0.2)
    assert len(pod_names) == 3
    assert http.post("/tasks", json={"definition": "native", "key": "fourth"}).json() == {
        "kind": "instance_budget_exhausted",
    }


def test_coordinator_death_has_independent_deadline(control):
    http, process, core, namespace = control
    response = http.post("/tasks", json={"definition": "native", "key": "agent"})
    response.raise_for_status()
    assert run(http, "agent", "echo running")["stdout"] == "running\n"
    name = response.json()["pod_name"]
    process.kill()
    process.wait(timeout=10)
    until = time.monotonic() + 90
    while True:
        pod = core.read_namespaced_pod(name, namespace)
        if pod.status.phase == "Failed":
            assert pod.status.reason == "DeadlineExceeded" or any(
                status.name == "task"
                and status.state.terminated is not None
                and status.state.terminated.exit_code == 124
                for status in pod.status.container_statuses
            )
            break
        assert time.monotonic() < until, "task survived its independent deadline"
        time.sleep(0.5)


def test_command_timeout_destroys_environment(control):
    http, process, core, namespace = control
    response = http.post("/tasks", json={"definition": "native", "key": "agent"})
    response.raise_for_status()
    assert run(http, "agent", "echo ready")["kind"] == "completed"
    result = run(http, "agent", "echo started; echo diagnostic >&2; sleep 60 & wait", timeout=1)
    assert result["kind"] == "timeout"
    assert result["stdout"] == "started\n"
    assert result["stderr"] == "diagnostic\n"
    assert run(http, "agent", "echo cannot-reuse")["kind"] == "closed"
    until = time.monotonic() + 20
    while core.list_namespaced_pod(namespace, label_selector="coworld-component=task").items:
        assert time.monotonic() < until, "command descendants survived timeout"
        time.sleep(0.2)


def test_task_network_isolation(control):
    http, process, core, namespace = control
    response = http.post("/tasks", json={"definition": "native", "key": "agent"})
    response.raise_for_status()
    api_ip = core.read_namespaced_service("kubernetes", "default").spec.cluster_ip
    result = run(
        http,
        "agent",
        (f"python -c \"import socket; s=socket.socket(); s.settimeout(2); print(s.connect_ex(('{api_ip}',443)))\""),
    )
    assert result["kind"] == "completed"
    assert result["exit_code"] == 0
    assert result["stdout"].strip() != "0", "task can reach the Kubernetes API despite no-network policy"


def test_close_interrupts_active_command(control):
    http, process, core, namespace = control
    response = http.post("/tasks", json={"definition": "native", "key": "agent"})
    response.raise_for_status()
    name = response.json()["pod_name"]
    assert run(http, "agent", "echo ready")["kind"] == "completed"
    with ThreadPoolExecutor(max_workers=1) as executor:
        command = executor.submit(run, http, "agent", "touch /tmp/started; sleep 60 & wait", 30)
        until = time.monotonic() + 10
        while True:
            started = stream(
                core.connect_get_namespaced_pod_exec,
                name,
                namespace,
                container="task",
                _request_timeout=5,
                command=["/bin/sh", "-c", "test -e /tmp/started && echo started"],
                stderr=True,
                stdout=True,
            )
            if started.strip() == "started":
                break
            assert time.monotonic() < until, "command never started"
            time.sleep(0.1)
        assert http.delete("/tasks/agent", timeout=10).status_code == 200
        assert command.result(timeout=10)["kind"] == "closed"
    assert run(http, "agent", "echo cannot-reuse")["kind"] == "closed"
    until = time.monotonic() + 20
    while core.list_namespaced_pod(namespace, label_selector="coworld-component=task").items:
        assert time.monotonic() < until, "command descendants survived cancellation"
        time.sleep(0.2)


def test_evidence_failure_does_not_prevent_cleanup(control, tmp_path: Path):
    http, process, core, namespace = control
    response = http.post("/tasks", json={"definition": "native", "key": "agent"})
    response.raise_for_status()
    assert run(http, "agent", "echo ready")["kind"] == "completed"
    evidence = tmp_path / "evidence" / (response.json()["pod_name"] + ".jsonl")
    evidence.rename(evidence.with_suffix(".preserved.jsonl"))
    evidence.mkdir()
    assert http.delete("/tasks/agent", headers={"Connection": "close"}).status_code == 500
    assert run(http, "agent", "echo cannot-reuse")["kind"] == "closed"
    until = time.monotonic() + 20
    while core.list_namespaced_pod(namespace, label_selector="coworld-component=task").items:
        assert time.monotonic() < until, "evidence failure prevented cleanup"
        time.sleep(0.2)


def test_shutdown_closes_all_environments(control):
    http, process, core, namespace = control
    for key in ("agent", "verifier"):
        response = http.post("/tasks", json={"definition": "native", "key": key})
        response.raise_for_status()
        assert run(http, key, "echo ready")["kind"] == "completed"
    assert len(core.list_namespaced_pod(namespace, label_selector="coworld-component=task").items) == 2
    process.terminate()
    process.wait(timeout=30)
    until = time.monotonic() + 20
    while core.list_namespaced_pod(namespace, label_selector="coworld-component=task").items:
        assert time.monotonic() < until, "tasks survived coordinator shutdown"
        time.sleep(0.2)


def test_startup_timeout_is_not_command_timeout(control):
    http, process, core, namespace = control
    response = http.post("/tasks", json={"definition": "unavailable", "key": "agent"})
    response.raise_for_status()
    assert run(http, "agent", "echo never-started", timeout=0.01)["kind"] == "startup_timeout"
    assert run(http, "agent", "echo cannot-reuse")["kind"] == "closed"
    until = time.monotonic() + 20
    while core.list_namespaced_pod(namespace, label_selector="coworld-component=task").items:
        assert time.monotonic() < until, "failed startup left a task pod"
        time.sleep(0.2)


@pytest.mark.parametrize("control", [True], indirect=True)
def test_files_and_network_phases(control, tmp_path: Path):
    http, process, core, namespace = control
    token = http.headers["Authorization"].removeprefix("Bearer ")
    contents = bytes(range(256)) * 8192
    source = tmp_path / "input.bin"
    source.write_bytes(contents)
    with TaskEnvironmentClient(str(http.base_url), token, timeout_seconds=40) as tasks:
        task = tasks.create(CreateTask(definition="native", key="agent"))
        pod = core.read_namespaced_pod(task.pod_name, namespace)
        assert next(container.image for container in pod.spec.containers if container.name == "task") == task.image
        try:
            uploaded = tasks.upload(task, source, "/tmp/input.bin")
            assert uploaded.kind == "completed" and uploaded.exit_code == 0
            tasks.download(task, "/tmp/input.bin", tmp_path / "download.bin")
            assert (tmp_path / "download.bin").read_bytes() == contents
            public = tasks.execute(
                task,
                ExecuteTask(
                    command=[
                        "python",
                        "-c",
                        "import urllib.request; print(urllib.request.urlopen('https://example.com', timeout=5).status)",
                    ],
                    timeout_seconds=10,
                ),
            )
            assert public.kind == "completed" and public.stdout.strip() == "200"
            assert tasks.set_network(task, NetworkPhase(mode="no-network")).exit_code == 0
            blocked = tasks.execute(
                task,
                ExecuteTask(
                    command=["python", "-c", "import socket; socket.create_connection(('1.1.1.1',443),timeout=2)"],
                    timeout_seconds=10,
                ),
            )
            assert blocked.kind == "completed" and blocked.exit_code != 0
            tasks.download(task, "/tmp/input.bin", tmp_path / "offline.bin")
            assert (tmp_path / "offline.bin").read_bytes() == contents
            assert tasks.set_network(task, NetworkPhase(mode="public")).exit_code == 0
            assert http.post("/tasks/agent/network", json={"mode": "no-network"}).status_code == 409
        finally:
            assert tasks.close_task(task).kind == "closed"


@pytest.mark.parametrize("control", ["coding"], indirect=True)
@pytest.mark.parametrize("pressure", ["pids", "memory"])
def test_coding_isolation_and_shared_quota(control, pressure: str):
    http, process, core, namespace = control
    created = http.post("/tasks", json={"definition": "native", "key": "coding"})
    created.raise_for_status()
    try:
        profile = run(
            http,
            "coding",
            "python -c 'import json,os,resource; from pathlib import Path; "
            'print(json.dumps({"uid":os.getuid(),"gid":os.getgid(),'
            '"readonly":bool(os.statvfs("/").f_flag & os.ST_RDONLY),'
            '"scratch_bytes":os.statvfs("/tmp").f_blocks*os.statvfs("/tmp").f_frsize,'
            '"stack":resource.getrlimit(resource.RLIMIT_STACK),'
            '"status":Path("/proc/self/status").read_text(),'
            '"swap":Path("/sys/fs/cgroup/memory.swap.max").read_text(),'
            '"oom_group":Path("/sys/fs/cgroup/memory.oom.group").read_text()}))\'',
        )
        assert profile["kind"] == "completed" and profile["exit_code"] == 0
        observed = json.loads(profile["stdout"])
        assert observed["uid"] == observed["gid"] == 65534
        assert observed["readonly"]
        assert observed["scratch_bytes"] == 1024**3
        assert observed["stack"] == [8 * 1024**3, 8 * 1024**3]
        assert "CapEff:\t0000000000000000" in observed["status"]
        assert observed["swap"].strip() == "0"
        assert observed["oom_group"].strip() == "1"
        blocked = run(
            http, "coding", "python -c \"import socket; socket.create_connection(('1.1.1.1',443),timeout=2)\""
        )
        assert blocked["kind"] == "completed" and blocked["exit_code"] != 0
        # A second task from the same episode competes for the namespace-wide
        # quota also used by separate certification and evaluation episodes.
        # A rejected competing caller must not reuse the grading caller's HTTP
        # connection after the server closes its failed creation request.
        with httpx.Client(base_url=http.base_url, headers=http.headers, timeout=40) as competing:
            second = competing.post("/tasks", json={"definition": "native", "key": "competing"})
        assert second.status_code == 500
        assert len(core.list_namespaced_pod(namespace, label_selector="coworld-component=task").items) == 1
        if pressure == "pids":
            exhausted = run(
                http,
                "coding",
                "python -c 'import subprocess; children=[]; "
                '[ (children.append(subprocess.Popen(["sleep","30"],'
                "stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)), print(len(children),flush=True)) "
                "for _ in range(300) ]'",
            )
            assert exhausted["kind"] == "completed" and exhausted["exit_code"] != 0
            assert 200 <= int(exhausted["stdout"].splitlines()[-1]) < 256
        else:
            # Only the owned 1 GiB task is exhausted; the kind node has its own
            # independent memory cap. Native benchmark budgets remain unchanged.
            exhausted = run(http, "coding", "python -c 'x=bytearray(2*1024*1024*1024); print(len(x))'")
            assert exhausted["kind"] in {"task_terminated", "completion_unknown"} or (
                exhausted["kind"] == "completed" and exhausted["exit_code"] == 137
            )
            until = time.monotonic() + 20
            while True:
                pod = core.read_namespaced_pod(created.json()["pod_name"], namespace)
                task_status = next(status for status in pod.status.container_statuses if status.name == "task")
                if task_status.state.terminated is not None:
                    assert task_status.state.terminated.reason == "OOMKilled"
                    assert task_status.state.terminated.exit_code == 137
                    break
                assert time.monotonic() < until, "Task supervisor survived memory exhaustion"
                time.sleep(0.2)
    finally:
        assert http.delete("/tasks/coding").status_code == 200
    until = time.monotonic() + 20
    while core.list_namespaced_pod(namespace, label_selector="coworld-component=task").items:
        assert time.monotonic() < until, "Coding reservation outlived cleanup"
        time.sleep(0.2)
    while core.read_namespaced_resource_quota("coworld-coding-tasks", namespace).status.used["pods"] != "0":
        assert time.monotonic() < until, "Coding quota did not release after task deletion"
        time.sleep(0.2)
