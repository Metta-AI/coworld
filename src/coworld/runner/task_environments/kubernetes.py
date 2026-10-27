"""Coordinator-owned task pods with non-renewable lifetimes.

The caller owns admission. Each task has an independent process deadline and
network guard; the game cannot choose images or change its admitted budgets.
"""

from __future__ import annotations

import hashlib
import math
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Annotated, Literal

from kubernetes import client
from kubernetes.stream import stream
from kubernetes.stream.ws_client import ERROR_CHANNEL
from pydantic import BaseModel, Field, Json, TypeAdapter

from coworld.runner.task_environments.network import PRIVATE_IPV4
from coworld.task_environment import CommandResult, TaskHandle
from coworld.types import CoworldTaskEnvironment

TASK_LABEL = "coworld-task-owner"
API_TIMEOUT = (5, 15)


class ExecStatusCause(BaseModel):
    reason: Literal["ExitCode"]
    message: int = Field(gt=0, le=255)


class ExecStatusDetails(BaseModel):
    causes: list[ExecStatusCause] = Field(default_factory=list)


class ExecStatus(BaseModel):
    status: Literal["Success", "Failure"]
    reason: str = ""
    details: ExecStatusDetails = Field(default_factory=ExecStatusDetails)


_EXEC_STATUS_ADAPTER = TypeAdapter(Annotated[Json[ExecStatus] | str, Field(union_mode="left_to_right")])


class TaskRejection(ValueError):
    def __init__(self, kind: str) -> None:
        self.kind = kind
        super().__init__(kind)


class TaskPods:
    """One coordinator's serial task operations; never share across episodes.

    A key is consumed before creating its pod. A failed create cannot be retried
    as a new environment. Cleanup discovers pods by ownership, including a pod
    whose creation response was lost. Closed keys cannot create fresh state.
    """

    def __init__(
        self,
        api: client.ApiClient,
        *,
        namespace: str,
        owner_name: str,
        owner_uid: str,
        expires_at: datetime,
        definitions: dict[str, CoworldTaskEnvironment],
        evidence_dir: Path,
        guard_image: str,
        owner_labels: dict[str, str] | None = None,
        node_selector: dict[str, str] | None = None,
        tolerations: list[client.V1Toleration] | None = None,
    ) -> None:
        if expires_at.tzinfo is None or expires_at <= datetime.now(UTC):
            raise ValueError("Task deadline must be an aware future timestamp")
        self.owner_labels = owner_labels or {}
        self.node_selector = node_selector
        self.tolerations = tolerations
        self.guard_image = guard_image
        self.network_steps: dict[str, int] = {}
        self.core = client.CoreV1Api(api)
        self.network = client.NetworkingV1Api(api)
        self.namespace = namespace
        self.owner_uid = owner_uid
        self.owner = client.V1OwnerReference(api_version="v1", kind="Pod", name=owner_name, uid=owner_uid)
        self.expires_at = expires_at
        self.definitions = definitions
        self.evidence_dir = evidence_dir
        self.evidence_dir.mkdir(parents=True, exist_ok=False)
        self.handles: dict[str, TaskHandle] = {}
        self.closed: set[str] = set()
        self.cancelled: set[str] = set()
        self.accepting = True
        self.lock = RLock()

    def _record_failure(self, result: CommandResult) -> None:
        # The worker reads concurrently; publish only complete JSON receipts.
        pending = self.evidence_dir / "failure.pending"
        pending.write_text(result.model_dump_json())
        pending.replace(self.evidence_dir / "failure.json")

    def create(self, definition: str, key: str) -> TaskHandle:
        with self.lock:
            if not self.accepting or key in self.closed or key in self.cancelled:
                raise TaskRejection("task_closed")
            if key in self.handles:
                handle = self.handles[key]
                if handle.definition != definition:
                    raise TaskRejection("key_conflict")
                return handle
            declared = self.definitions[definition]
            coding = declared.isolation == "coding"
            if coding:
                quota = self.core.read_namespaced_resource_quota(
                    "coworld-coding-tasks", self.namespace, _request_timeout=API_TIMEOUT
                )
                if (
                    quota.spec.hard != {"pods": "1"}
                    or quota.spec.scope_selector
                    != client.V1ScopeSelector(
                        match_expressions=[
                            client.V1ScopedResourceSelectorRequirement(
                                scope_name="PriorityClass", operator="In", values=["coworld-coding-task"]
                            )
                        ]
                    )
                    or quota.spec.scopes
                ):
                    raise TaskRejection("coding_quota_mismatch")
                if quota.metadata.deletion_timestamp is not None:
                    raise TaskRejection("coding_quota_deleting")
            if sum(handle.definition == definition for handle in self.handles.values()) >= declared.max_instances:
                raise TaskRejection("instance_budget_exhausted")
            definition_pods = {handle.pod_name for handle in self.handles.values() if handle.definition == definition}
            pods = self.core.list_namespaced_pod(
                self.namespace, label_selector=f"{TASK_LABEL}={self.owner_uid}", _request_timeout=API_TIMEOUT
            ).items
            if sum(pod.metadata.name in definition_pods for pod in pods) >= declared.max_concurrent_instances:
                raise TaskRejection("concurrency_budget_exhausted")
            if not re.fullmatch(r".+@sha256:[a-f0-9]{64}", declared.image):
                raise TaskRejection("unresolved_task_image")
            lifetime = math.floor((self.expires_at - datetime.now(UTC)).total_seconds())
            if lifetime <= 0:
                raise TaskRejection("episode_expired")
            digest = hashlib.sha256(f"{self.owner_uid}/{key}".encode()).hexdigest()[:32]
            name = f"coworld-task-{digest}"
            handle = TaskHandle(
                key=key, definition=definition, pod_name=name, image=declared.image, expires_at=self.expires_at
            )
            self.handles[key] = handle
            self.network_steps[key] = 0
            # Failures during creation leave the key closed and cleanup discoverable.
            self.closed.add(key)
            labels = {
                **self.owner_labels,
                TASK_LABEL: self.owner_uid,
                "coworld-component": "task",
                "coworld-task": name,
            }
            if coding:
                labels["coworld-coding-execution"] = "true"
            metadata = client.V1ObjectMeta(name=name, labels=labels, owner_references=[self.owner])
            created = False
            try:
                self.network.create_namespaced_network_policy(
                    self.namespace,
                    client.V1NetworkPolicy(
                        metadata=metadata,
                        spec=client.V1NetworkPolicySpec(
                            pod_selector=client.V1LabelSelector(match_labels={"coworld-task": name}),
                            policy_types=["Ingress", "Egress"],
                            ingress=[],
                            egress=(
                                [
                                    client.V1NetworkPolicyEgressRule(
                                        to=[
                                            client.V1NetworkPolicyPeer(
                                                ip_block=client.V1IPBlock(cidr="0.0.0.0/0", _except=list(PRIVATE_IPV4))
                                            )
                                        ]
                                    )
                                ]
                            ),
                        ),
                    ),
                    _request_timeout=API_TIMEOUT,
                )
                quantities = {
                    "cpu": f"{declared.cpu_millis}m",
                    "memory": f"{declared.memory_mib}Mi",
                    "ephemeral-storage": f"{declared.storage_mib}Mi",
                }
                volumes = [client.V1Volume(name="task-runtime", empty_dir=client.V1EmptyDirVolumeSource())]
                mounts = [client.V1VolumeMount(name="task-runtime", mount_path="/coworld-runtime", read_only=True)]
                if coding:
                    volumes.append(
                        client.V1Volume(
                            name="task-scratch",
                            empty_dir=client.V1EmptyDirVolumeSource(medium="Memory", size_limit="1Gi"),
                        )
                    )
                    mounts.append(client.V1VolumeMount(name="task-scratch", mount_path="/tmp"))
                pod = self.core.create_namespaced_pod(
                    self.namespace,
                    client.V1Pod(
                        metadata=client.V1ObjectMeta(
                            name=name,
                            labels=labels,
                            owner_references=[self.owner],
                            annotations={"karpenter.sh/do-not-disrupt": "true"},
                        ),
                        spec=client.V1PodSpec(
                            restart_policy="Never",
                            priority_class_name="coworld-coding-task" if coding else None,
                            node_selector={"workload-type": "coworld-coding-tasks"} if coding else self.node_selector,
                            tolerations=[
                                client.V1Toleration(
                                    key="workload-type",
                                    operator="Equal",
                                    value="coworld-coding-tasks",
                                    effect="NoSchedule",
                                )
                            ]
                            if coding
                            else self.tolerations,
                            active_deadline_seconds=lifetime,
                            termination_grace_period_seconds=1,
                            automount_service_account_token=False,
                            enable_service_links=False,
                            dns_policy="None",
                            dns_config=client.V1PodDNSConfig(nameservers=["1.1.1.1", "8.8.8.8"]),
                            init_containers=([self._guard("task-network-init", declared.network)]),
                            volumes=volumes,
                            containers=[
                                self._guard("task-network", "wait"),
                                client.V1Container(
                                    name="task",
                                    image=declared.image,
                                    image_pull_policy="IfNotPresent",
                                    command=(
                                        ["/coworld-runtime/supervisor", str(math.floor(self.expires_at.timestamp()))]
                                    ),
                                    volume_mounts=mounts,
                                    resources=client.V1ResourceRequirements(requests=quantities, limits=quantities),
                                    security_context=client.V1SecurityContext(
                                        allow_privilege_escalation=False,
                                        run_as_user=65534 if coding else None,
                                        run_as_group=65534 if coding else None,
                                        run_as_non_root=True if coding else None,
                                        read_only_root_filesystem=coding,
                                        capabilities=client.V1Capabilities(
                                            drop=["ALL"],
                                            add=[]
                                            if coding
                                            else [
                                                "CHOWN",
                                                "DAC_OVERRIDE",
                                                "FOWNER",
                                                "FSETID",
                                                "KILL",
                                                "SETGID",
                                                "SETUID",
                                                "SETFCAP",
                                            ],
                                        ),
                                        seccomp_profile=client.V1SeccompProfile(type="RuntimeDefault"),
                                    ),
                                ),
                            ],
                        ),
                    ),
                    _request_timeout=API_TIMEOUT,
                )
                self._record(handle, "created", pod)
                if key in self.cancelled or not self.accepting:
                    self._close(handle)
                    raise TaskRejection("task_closed")
                self.closed.remove(key)
                created = True
                return handle
            finally:
                if not created:
                    try:
                        self._record_failure(CommandResult(kind="completion_unknown"))
                    finally:
                        self._close(handle)

    def _guard(self, name: str, mode: str) -> client.V1Container:
        return client.V1Container(
            name=name,
            image=self.guard_image,
            image_pull_policy="IfNotPresent",
            command=(
                [
                    "/bin/sh",
                    "-c",
                    "cp /opt/coworld-task-supervisor /coworld-runtime/supervisor && "
                    f"exec python -m coworld.runner.task_environments.network {mode}",
                ]
                if name == "task-network-init"
                else ["/opt/coworld-task-supervisor", str(math.floor(self.expires_at.timestamp()))]
            ),
            volume_mounts=[client.V1VolumeMount(name="task-runtime", mount_path="/coworld-runtime")]
            if name == "task-network-init"
            else [],
            resources=client.V1ResourceRequirements(
                requests={"cpu": "25m", "memory": "32Mi"}, limits={"cpu": "100m", "memory": "128Mi"}
            ),
            security_context=client.V1SecurityContext(
                run_as_user=0,
                allow_privilege_escalation=False,
                capabilities=client.V1Capabilities(drop=["ALL"], add=["NET_ADMIN"]),
                seccomp_profile=client.V1SeccompProfile(type="RuntimeDefault"),
            ),
        )

    def set_network(self, key: str, mode: Literal["public", "no-network"]) -> CommandResult:
        with self.lock:
            handle = self.handles[key]
            declared = self.definitions[handle.definition]
            phases = [declared.network, *declared.network_transitions]
            step = self.network_steps[key]
            if mode == phases[step]:
                return CommandResult(kind="completed", exit_code=0)
            if step + 1 == len(phases) or mode != phases[step + 1]:
                raise TaskRejection("undeclared_network_transition")
            result = self.execute(
                key,
                ["python", "-m", "coworld.runner.task_environments.network", mode],
                20,
                65536,
                container="task-network",
            )
            if result.kind == "completed" and result.exit_code == 0:
                self.network_steps[key] = step + 1
                self._record(
                    handle,
                    f"network:{mode}",
                    self.core.read_namespaced_pod(handle.pod_name, self.namespace, _request_timeout=API_TIMEOUT),
                )
            else:
                self.close(key)
            return result

    def execute(
        self,
        key: str,
        command: list[str],
        timeout_seconds: float,
        max_output_bytes: int,
        *,
        container: str = "task",
        input_path: Path | None = None,
        output_path: Path | None = None,
    ) -> CommandResult:
        with self.lock:
            handle = self.handles[key]
            if not self.accepting or key in self.closed or key in self.cancelled:
                return CommandResult(kind="closed")
            episode_deadline = time.monotonic() + (self.expires_at - datetime.now(UTC)).total_seconds()
            startup_deadline = min(
                time.monotonic() + self.definitions[handle.definition].startup_timeout_seconds, episode_deadline
            )
            while time.monotonic() < startup_deadline:
                if not self.accepting or key in self.cancelled:
                    self._close(handle)
                    return CommandResult(kind="closed")
                pod = self.core.read_namespaced_pod(handle.pod_name, self.namespace, _request_timeout=API_TIMEOUT)
                statuses = pod.status.container_statuses or []
                if any(status.name == "task" and status.state.running is not None for status in statuses):
                    break
                if pod.status.phase in {"Failed", "Succeeded"} or any(
                    status.name == "task" and status.state.terminated is not None for status in statuses
                ):
                    self._close(handle)
                    result = CommandResult(kind="task_terminated")
                    self._record_failure(result)
                    return result
                time.sleep(0.2)
            else:
                self._close(handle)
                result = CommandResult(kind="startup_timeout")
                self._record_failure(result)
                return result
            deadline = min(time.monotonic() + timeout_seconds, episode_deadline)
            complete = False
            try:
                if container == "task" and self.definitions[handle.definition].isolation == "coding":
                    command = ["/bin/sh", "-ec", 'ulimit -s 8388608; exec "$@"', "coding-task", *command]
                connection = stream(
                    self.core.connect_get_namespaced_pod_exec,
                    handle.pod_name,
                    self.namespace,
                    container=container,
                    command=command,
                    stderr=True,
                    stdout=True,
                    stdin=input_path is not None,
                    binary=True,
                    tty=False,
                    _preload_content=False,
                    _request_timeout=API_TIMEOUT,
                )
                with ExitStack() as files:
                    source = files.enter_context(input_path.open("rb")) if input_path is not None else None
                    target = files.enter_context(output_path.open("wb")) if output_path is not None else None
                    result = self._command_stream(handle, connection, source, target, deadline, max_output_bytes)
                complete = result.kind == "completed"
                if result.kind not in {"completed", "closed"}:
                    self._record_failure(result)
                with (self.evidence_dir / f"{handle.pod_name}-commands.jsonl").open("a") as log:
                    log.write(result.model_dump_json() + "\n")
                return result
            finally:
                if not complete:
                    try:
                        if sys.exception() is not None:
                            self._record_failure(CommandResult(kind="completion_unknown"))
                    finally:
                        self._close(handle)

    def _command_stream(self, handle, connection, source, target, deadline, max_output_bytes) -> CommandResult:
        key = handle.key
        stdout: list[str] = []
        stderr: list[str] = []
        size = 0
        next_ping = time.monotonic() + 5
        try:
            while connection.is_open():
                if not self.accepting or key in self.cancelled:
                    return CommandResult(kind="closed", stdout="".join(stdout), stderr="".join(stderr))
                if time.monotonic() >= deadline:
                    return CommandResult(kind="timeout", stdout="".join(stdout), stderr="".join(stderr))
                if time.monotonic() >= next_ping:
                    # Silent commands must keep the relay tunnel active without changing their output.
                    connection.sock.ping()
                    next_ping = time.monotonic() + 5
                if source is not None:
                    chunk = source.read(65536)
                    if chunk:
                        connection.write_stdin(chunk)
                connection.update(
                    timeout=0 if source is not None and chunk else min(0.2, max(0, deadline - time.monotonic()))
                )
                for chunks, value in (
                    (stdout, connection.read_stdout(timeout=0)),
                    (stderr, connection.read_stderr(timeout=0)),
                ):
                    size += len(value)
                    if size > max_output_bytes:
                        return CommandResult(kind="output_limit", stdout="".join(stdout), stderr="".join(stderr))
                    if target is not None and chunks is stdout:
                        target.write(value)
                    else:
                        chunks.append(value.decode("utf-8", errors="replace"))
            status_payload = connection.read_channel(ERROR_CHANNEL, timeout=0)
            if not status_payload:
                return CommandResult(kind="completion_unknown", stdout="".join(stdout), stderr="".join(stderr))
            status_text = status_payload.decode("utf-8", errors="replace")
            status = _EXEC_STATUS_ADAPTER.validate_python(status_text)
            if isinstance(status, ExecStatus) and status.status == "Success":
                exit_code = 0
            elif (
                isinstance(status, ExecStatus)
                and status.reason == "NonZeroExitCode"
                and len(status.details.causes) == 1
            ):
                exit_code = status.details.causes[0].message
            else:
                # API/kubelet failures carry text causes, not process exit codes.
                return CommandResult(
                    kind="completion_unknown",
                    stdout="".join(stdout),
                    stderr="".join(stderr) + status_text,
                )
            return CommandResult(kind="completed", stdout="".join(stdout), stderr="".join(stderr), exit_code=exit_code)
        finally:
            try:
                connection.close()
            finally:
                # A received close frame can leave websocket-client's TCP socket open.
                connection.sock.shutdown()

    def close(self, key: str) -> None:
        self.cancelled.add(key)
        with self.lock:
            self._close(self.handles[key])

    def _close(self, handle: TaskHandle) -> None:
        self.closed.add(handle.key)
        pods = self.core.list_namespaced_pod(
            self.namespace, label_selector=f"{TASK_LABEL}={self.owner_uid}", _request_timeout=API_TIMEOUT
        ).items
        for pod in pods:
            if pod.metadata.name == handle.pod_name:
                self._delete_pod(pod)
        # Deny policies remain until parent GC; removing them while a pod is
        # terminating could reopen its network.

    def close_all(self) -> None:
        self.accepting = False
        with self.lock:
            pods = self.core.list_namespaced_pod(
                self.namespace, label_selector=f"{TASK_LABEL}={self.owner_uid}", _request_timeout=API_TIMEOUT
            ).items
            self.closed.update(self.handles)
            # Submit every deletion before observing failures. The executor waits
            # for all attempts even when one result raises.
            with ThreadPoolExecutor(max_workers=4) as cleanup:
                deletions = [cleanup.submit(self._delete_pod, pod) for pod in pods]
                for deletion in deletions:
                    deletion.result()

    def _delete_pod(self, pod: client.V1Pod) -> None:
        handle = next(handle for handle in self.handles.values() if handle.pod_name == pod.metadata.name)
        try:
            self._record(handle, "closing", pod)
        finally:
            # Collection deletion succeeds if a prior close or GC already removed
            # the pod. Select exactly this owner/name and retain the UID guard.
            self.core.delete_collection_namespaced_pod(
                self.namespace,
                field_selector=f"metadata.name={pod.metadata.name}",
                label_selector=f"{TASK_LABEL}={self.owner_uid}",
                body=client.V1DeleteOptions(preconditions=client.V1Preconditions(uid=pod.metadata.uid)),
                _request_timeout=API_TIMEOUT,
            )

    def _record(self, handle: TaskHandle, event: str, pod: client.V1Pod) -> None:
        path = self.evidence_dir / f"{handle.pod_name}.jsonl"
        with path.open("a", encoding="utf-8") as output:
            output.write(
                TaskEvidence(
                    handle=handle,
                    event=event,
                    at=datetime.now(UTC),
                    pod_uid=pod.metadata.uid,
                    phase=pod.status.phase or "Pending",
                    status=self.core.api_client.sanitize_for_serialization(pod.status),
                ).model_dump_json()
                + "\n"
            )


class TaskEvidence(BaseModel):
    handle: TaskHandle
    event: str
    at: datetime
    pod_uid: str
    phase: str
    status: dict
