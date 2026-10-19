"""Explicit local game containment for controller-qualified file runtimes."""

import os
import subprocess
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


class GameSandboxSettings(BaseModel):
    GroupAdd: list[str] | None = None
    CapAdd: list[str] | None
    CapDrop: list[str]
    SecurityOpt: list[str]
    Privileged: bool
    ReadonlyRootfs: bool
    PidsLimit: int
    Tmpfs: dict[str, str]


class GameSandboxIdentity(BaseModel):
    User: str


class GameSandboxReceipt(BaseModel):
    Id: str
    Image: str
    Config: GameSandboxIdentity
    HostConfig: GameSandboxSettings


class LocalGameSandbox(BaseModel):
    """Fixed restrictions plus bounded scratch and process allowances; not seat isolation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    protocol: Literal["coworld.local-game-sandbox.v1"] = "coworld.local-game-sandbox.v1"
    uid: int = Field(default=1000, gt=0)
    gid: int = Field(default=1000, gt=0)
    pids: int = Field(default=512, gt=0)
    temporary_bytes: int = Field(default=128 * 1024**2, gt=0)

    @property
    def workspace_gid(self) -> int:
        """Root controllers assign the profile group; ordinary controllers share their own group."""
        group = self.gid if os.getuid() == 0 else os.getgid()
        if group == 0:
            raise ValueError("Sandbox workspace requires a non-root group")
        return group

    def docker_args(self) -> list[str]:
        return [
            "--user",
            f"{self.uid}:{self.gid}",
            "--group-add",
            str(self.workspace_gid),
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--read-only",
            f"--pids-limit={self.pids}",
            "--tmpfs",
            f"/tmp:rw,nosuid,nodev,size={self.temporary_bytes}",
        ]

    def prepare_workspace(self, workspace: Path) -> None:
        """Grant the game the controller's group access inside its explicit writable mount."""
        paths = [workspace, *workspace.rglob("*")]
        for path in paths:
            if path.is_symlink() or path.stat().st_uid != os.getuid():
                raise ValueError(f"Sandbox workspace must contain only controller-owned paths: {path}")
        for path in paths:
            os.chown(path, -1, self.workspace_gid)
            path.chmod(0o2770 if path.is_dir() else 0o660)

    def inspect(self, container: str) -> GameSandboxReceipt:
        """Validate Docker's actual configuration before starting candidate execution."""
        inspected = subprocess.check_output(["docker", "inspect", container], timeout=30)
        (receipt,) = TypeAdapter(list[GameSandboxReceipt]).validate_json(inspected)
        settings = receipt.HostConfig
        if (
            receipt.Config.User != f"{self.uid}:{self.gid}"
            or settings.GroupAdd != [str(self.workspace_gid)]
            or settings.CapAdd
            or settings.CapDrop != ["ALL"]
            or settings.SecurityOpt != ["no-new-privileges"]
            or settings.Privileged
            or not settings.ReadonlyRootfs
            or settings.PidsLimit != self.pids
            or settings.Tmpfs != {"/tmp": f"rw,nosuid,nodev,size={self.temporary_bytes}"}
        ):
            raise ValueError("Game container differs from its requested sandbox")
        return receipt
