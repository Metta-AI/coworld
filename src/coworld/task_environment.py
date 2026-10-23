"""Typed client for the episode-local task service; command requests are never retried."""

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import Annotated, Literal, Self
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field

MAX_FILE_BYTES = 200 * 1024 * 1024


class TaskHandle(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str
    definition: str
    pod_name: str
    image: str = Field(pattern=r"^.+@sha256:[a-f0-9]{64}$")
    expires_at: datetime


class CommandResult(BaseModel):
    kind: Literal[
        "completed", "timeout", "output_limit", "closed", "completion_unknown", "startup_timeout", "task_terminated"
    ]
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None


class CreateTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    definition: str = Field(min_length=1, max_length=64)
    key: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


class ExecuteTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: list[Annotated[str, Field(max_length=65536)]] = Field(min_length=1, max_length=64)
    timeout_seconds: float = Field(
        gt=0, le=86400, allow_inf_nan=False, description="Command execution budget after the task pod is running."
    )
    max_output_bytes: int = Field(default=65536, ge=1, le=1048576)


class NetworkPhase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["public", "no-network"]


class ClosedTask(BaseModel):
    kind: Literal["closed"] = "closed"


class TaskEnvironmentClient:
    """One game's authenticated task interface, without automatic transport retries.

    Callers own task lifetime and close their tasks in a finally block. A lost
    command response is uncertain execution, not permission to repeat the command.
    """

    def __init__(self, endpoint: str, token: str, *, timeout_seconds: float) -> None:
        self.http = httpx.Client(
            base_url=endpoint.rstrip("/"),
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout_seconds,
            trust_env=False,
            transport=httpx.HTTPTransport(retries=0),
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc_value: BaseException | None, traceback: TracebackType | None
    ) -> None:
        self.http.close()

    def create(self, request: CreateTask) -> TaskHandle:
        response = self.http.post("/tasks", json=request.model_dump(mode="json"))
        response.raise_for_status()
        return TaskHandle.model_validate_json(response.content)

    def execute(self, task: TaskHandle, request: ExecuteTask) -> CommandResult:
        response = self.http.post(f"/tasks/{quote(task.key, safe='')}/exec", json=request.model_dump(mode="json"))
        response.raise_for_status()
        return CommandResult.model_validate_json(response.content)

    def set_network(self, task: TaskHandle, phase: NetworkPhase) -> CommandResult:
        response = self.http.post(f"/tasks/{quote(task.key, safe='')}/network", json=phase.model_dump(mode="json"))
        response.raise_for_status()
        return CommandResult.model_validate_json(response.content)

    def upload(self, task: TaskHandle, source: Path, destination: str) -> CommandResult:
        if source.stat().st_size > MAX_FILE_BYTES:
            raise ValueError("Task file exceeds 200 MiB")

        def chunks() -> Iterator[bytes]:
            with source.open("rb") as stream:
                size = 0
                while chunk := stream.read(65536):
                    size += len(chunk)
                    if size > MAX_FILE_BYTES:
                        raise ValueError("Task file grew beyond 200 MiB during transfer")
                    yield chunk

        response = self.http.put(
            f"/tasks/{quote(task.key, safe='')}/file", params={"path": destination}, content=chunks()
        )
        response.raise_for_status()
        return CommandResult.model_validate_json(response.content)

    def download(self, task: TaskHandle, source: str, destination: Path) -> None:
        with self.http.stream("GET", f"/tasks/{quote(task.key, safe='')}/file", params={"path": source}) as response:
            response.raise_for_status()
            with destination.open("xb") as output:
                size = 0
                for chunk in response.iter_bytes(chunk_size=65536):
                    size += len(chunk)
                    if size > MAX_FILE_BYTES:
                        raise ValueError("Task download exceeds 200 MiB")
                    output.write(chunk)

    def close_task(self, task: TaskHandle) -> ClosedTask:
        response = self.http.delete(f"/tasks/{quote(task.key, safe='')}")
        response.raise_for_status()
        return ClosedTask.model_validate_json(response.content)
