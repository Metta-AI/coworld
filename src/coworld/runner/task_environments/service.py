"""Authenticated episode-local task control service.

Only the trusted coordinator supplies configuration and Kubernetes credentials.
The game receives a bearer token and can name declared environments, never pods
or images.
"""

from __future__ import annotations

import asyncio
import hmac
import shlex
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask
from starlette.types import Receive, Scope, Send

from coworld.runner.task_environments.kubernetes import TaskPods, TaskRejection
from coworld.task_environment import (
    MAX_FILE_BYTES,
    ClosedTask,
    CommandResult,
    CreateTask,
    ExecuteTask,
    NetworkPhase,
    TaskHandle,
)


class ReadyTaskControl(BaseModel):
    kind: Literal["ready"] = "ready"


class TaskControl:
    """ASGI boundary with bounded bodies and authentication before parsing."""

    def __init__(self, pods: TaskPods, token: str) -> None:
        if len(token) < 32:
            raise ValueError("Task control requires a random token of at least 32 characters")

        @asynccontextmanager
        async def lifespan(app: FastAPI):
            try:
                yield
            finally:
                await asyncio.to_thread(pods.close_all)

        self.app = FastAPI(lifespan=lifespan)

        @self.app.exception_handler(TaskRejection)
        async def rejected(request: Request, error: TaskRejection) -> JSONResponse:
            return JSONResponse(status_code=409, content={"kind": error.kind})

        @self.app.post("/tasks")
        def create(request: CreateTask) -> TaskHandle:
            if request.definition not in pods.definitions:
                raise HTTPException(status_code=404, detail="unknown_definition")
            return pods.create(request.definition, request.key)

        @self.app.post("/tasks/{key}/exec")
        def execute(key: str, request: ExecuteTask) -> CommandResult:
            if key not in pods.handles:
                raise HTTPException(status_code=404, detail="unknown_task")
            return pods.execute(key, request.command, request.timeout_seconds, request.max_output_bytes)

        @self.app.post("/tasks/{key}/network")
        def network(key: str, request: NetworkPhase) -> CommandResult:
            if key not in pods.handles:
                raise HTTPException(status_code=404, detail="unknown_task")
            return pods.set_network(key, request.mode)

        @self.app.put("/tasks/{key}/file")
        async def upload(key: str, path: str, request: Request) -> CommandResult:
            if key not in pods.handles:
                raise HTTPException(status_code=404, detail="unknown_task")
            if not path.startswith("/") or len(path) > 4096:
                raise HTTPException(status_code=422, detail="absolute_path_required")
            with tempfile.TemporaryDirectory(prefix="coworld-upload-") as directory:
                local = Path(directory) / "file"
                size = 0
                with local.open("wb") as output:
                    async for chunk in request.stream():
                        size += len(chunk)
                        if size > MAX_FILE_BYTES:
                            raise HTTPException(status_code=413, detail="file_too_large")
                        output.write(chunk)
                command = ["/bin/sh", "-c", f"head -c {size} > {shlex.quote(path)}"]
                return await asyncio.to_thread(pods.execute, key, command, 300, 65536, input_path=local)

        @self.app.get("/tasks/{key}/file")
        async def download(key: str, path: str):
            if key not in pods.handles:
                raise HTTPException(status_code=404, detail="unknown_task")
            if not path.startswith("/") or len(path) > 4096:
                raise HTTPException(status_code=422, detail="absolute_path_required")
            directory = tempfile.TemporaryDirectory(prefix="coworld-download-")
            local = Path(directory.name) / "file"
            delivered = False
            try:
                result = await asyncio.to_thread(
                    pods.execute,
                    key,
                    ["/bin/sh", "-c", f"cat -- {shlex.quote(path)}"],
                    300,
                    MAX_FILE_BYTES,
                    output_path=local,
                )
                if result.kind != "completed" or result.exit_code != 0:
                    return JSONResponse(status_code=409, content=result.model_dump())
                response = FileResponse(local, background=BackgroundTask(directory.cleanup))
                delivered = True
                return response
            finally:
                if not delivered:
                    directory.cleanup()

        @self.app.delete("/tasks")
        def close_all() -> ClosedTask:
            pods.close_all()
            return ClosedTask()

        @self.app.get("/healthz")
        def health() -> ReadyTaskControl:
            return ReadyTaskControl()

        @self.app.delete("/tasks/{key}")
        def close(key: str) -> ClosedTask:
            if key not in pods.handles:
                raise HTTPException(status_code=404, detail="unknown_task")
            pods.close(key)
            return ClosedTask()

        self.token = f"Bearer {token}".encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope["headers"])
        if not hmac.compare_digest(headers.get(b"authorization", b""), self.token):
            await self._reject(send, 401, b'{"kind":"invalid_task_credential"}')
            return
        if scope["method"] == "PUT" and scope["path"].endswith("/file"):
            await self.app(scope, receive, send)
            return
        # Read at most 64 KiB before handing a body to FastAPI/Pydantic. This
        # prevents oversized JSON from consuming the coordinator's memory.
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message["body"])
            if len(body) > 65536:
                await self._reject(send, 413, b'{"kind":"request_too_large"}')
                return
            if not message.get("more_body", False):
                break

        delivered = False

        async def bounded_receive():
            nonlocal delivered
            if delivered:
                return await receive()
            delivered = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        await self.app(scope, bounded_receive, send)

    @staticmethod
    async def _reject(send: Send, status: int, body: bytes) -> None:
        headers = [(b"content-type", b"application/json")]
        if status == 401:
            headers.append((b"www-authenticate", b"Bearer"))
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body})
