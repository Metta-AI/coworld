import os
import socket
import stat
import struct
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

CONTROL_DIR = Path("/var/run/coworld-pool")
GAME_UID = 65532


class ProcessStatus(BaseModel):
    state: Literal[0, 1, 2, 3]
    pid: int
    exit_code: int


def _string(value: str) -> bytes:
    encoded = value.encode() + b"\0"
    assert b"\0" not in encoded[:-1]
    return struct.pack("!I", len(encoded)) + encoded


def control(
    assignment: str,
    operation: Literal[0, 1, 2, 3],
    *,
    command: tuple[str, ...] = (),
    env: dict[str, str] | None = None,
    cwd: str = "/",
    timeout_seconds: int = 0,
) -> ProcessStatus:
    packet = struct.pack("!II", 1, operation) + _string(assignment)
    if operation == 1:
        assert env is not None
        packet += struct.pack("!I", timeout_seconds) + _string(cwd)
        for values in (command, tuple(f"{key}={value}" for key, value in env.items())):
            packet += struct.pack("!I", len(values)) + b"".join(_string(value) for value in values)
    assert len(packet) <= 1024 * 1024
    with socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET) as channel:
        channel.settimeout(10)
        channel.connect(str(CONTROL_DIR / "control.sock"))
        channel.sendall(packet)
        state, pid, exit_code = struct.unpack("!III", channel.recv(12))
    return ProcessStatus.model_validate({"state": state, "pid": pid, "exit_code": exit_code})


def require_clean_pool_outputs(workdir: Path) -> None:
    # Called after the namespace has no game processes, before trusted code writes outputs.
    # Reject links and special files rather than letting a root coordinator follow them.
    for directory, directories, files in os.walk(workdir, followlinks=False):
        for name in (*directories, *files):
            mode = (Path(directory) / name).lstat().st_mode
            if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                raise ValueError("Pool output contains a link or special file")
