"""Durable admission for controller-owned local Docker resources."""

import fcntl
import hashlib
import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field


class AdmissionState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    protocol: Literal["coworld.local-admission.v1"] = "coworld.local-admission.v1"
    owner: str = Field(min_length=1)
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    closed: bool = False
    operations: int = Field(default=0, ge=0)
    unresolved: list[int] = Field(default_factory=list)


@contextmanager
def local_resource_lock(path: Path) -> Iterator[int]:
    """Acquire a shared-open-description flock with a bounded wait."""
    with path.open("rb" if path.is_file() else "a") as lock:
        # flock belongs to the shared open-file description. The parent retains the lock after this
        # bounded helper exits; a blocked acquisition can be killed without swallowing an exception.
        subprocess.run(
            [
                sys.executable,
                "-I",
                "-S",
                "-c",
                "import fcntl,sys; fcntl.flock(int(sys.argv[1]), fcntl.LOCK_EX)",
                str(lock.fileno()),
            ],
            pass_fds=(lock.fileno(),),
            timeout=30,
            check=True,
        )
        try:
            yield lock.fileno()
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


class LocalResourceAdmission:
    """Keep this directory outside every container mount; controllers own its contents."""

    def __init__(self, root: Path, owner: str, request_sha256: str):
        self.root = root.resolve()
        self.owner = owner
        self.request_sha256 = request_sha256

    def initialize(self) -> None:
        self.root.mkdir(mode=0o700, parents=True, exist_ok=False)
        self._write(AdmissionState(owner=self.owner, request_sha256=self.request_sha256))

    def _write(self, state: AdmissionState) -> None:
        temporary = self.root / "state.pending"
        with temporary.open("w") as stream:
            stream.write(state.model_dump_json(indent=2) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(self.root / "state.json")
        descriptor = os.open(self.root, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @contextmanager
    def _locked(self) -> Iterator[tuple[int, AdmissionState]]:
        with local_resource_lock(self.root / "lock") as descriptor:
            state = AdmissionState.model_validate_json((self.root / "state.json").read_bytes())
            if (state.owner, state.request_sha256) != (self.owner, self.request_sha256):
                raise ValueError("Local resource admission belongs to another request or owner")
            yield descriptor, state

    def run(self, command: list[str], *, timeout_seconds: float, env: Mapping[str, str] | None = None) -> None:
        """Admit one bounded creation; uncertain daemon outcomes remain unresolved."""
        with self._locked() as (descriptor, state):
            if state.closed or state.unresolved:
                raise RuntimeError("Local resource admission is closed or has an unresolved Docker operation")
            operation = state.operations
            pending = state.model_copy(update={"operations": operation + 1, "unresolved": [operation]})
            self._write(pending)
            with (self.root / f"{operation:04}.command-sha256").open("w") as stream:
                stream.write(hashlib.sha256("\0".join(command).encode()).hexdigest() + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            with (self.root / f"{operation:04}.log").open("wb") as log:
                result = subprocess.run(
                    command,
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    timeout=timeout_seconds,
                    pass_fds=(descriptor,),
                )
                log.flush()
                os.fsync(log.fileno())
            # A failed CLI can leave an accepted daemon request in flight. Never infer absence from its exit.
            if result.returncode == 0:
                self._write(pending.model_copy(update={"unresolved": []}))
            result.check_returncode()

    def close(self) -> AdmissionState:
        """Fence future creation. Unresolved operations prohibit declaring cleanup complete."""
        with self._locked() as (_, state):
            closed = state.model_copy(update={"closed": True})
            self._write(closed)
            return closed
