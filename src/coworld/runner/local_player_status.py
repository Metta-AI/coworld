"""Capture Docker player state before runner cleanup changes its exit status."""

from __future__ import annotations

import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from coworld.runner.io import PlayerRuntimeStatus, PlayerRuntimeStatuses


class DockerPlayerState(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: str = Field(alias="Status")
    running: bool = Field(alias="Running")
    exit_code: int = Field(alias="ExitCode")
    oom_killed: bool = Field(alias="OOMKilled")
    error: str = Field(alias="Error")
    finished_at: str = Field(alias="FinishedAt")


class DockerPlayerInspection(BaseModel):
    model_config = ConfigDict(extra="ignore")

    container_id: str = Field(alias="Id")
    image_id: str = Field(alias="Image")
    state: DockerPlayerState = Field(alias="State")


class LocalPlayerReceipt(BaseModel):
    slot: int
    container_name: str
    inspection: DockerPlayerInspection


class LocalPlayerReceipts(BaseModel):
    schema_version: Literal["1"] = "1"
    observation: Literal["before_runner_cleanup"] = "before_runner_cleanup"
    players: list[LocalPlayerReceipt]


def collect_local_player_status(containers: list[str], player_count: int, workspace: Path) -> None:
    """Keep unknown/missing seats explicit; never attribute cleanup SIGKILL to a player."""
    statuses = [
        PlayerRuntimeStatus(slot=slot, state="not_started", reason="container_not_created")
        for slot in range(player_count)
    ]
    receipts = []
    for slot, name in enumerate(containers):
        result = subprocess.run(["docker", "inspect", name], capture_output=True, text=True, timeout=10)
        if result.returncode:
            statuses[slot] = PlayerRuntimeStatus(slot=slot, state="unavailable", reason="docker_inspect_failed")
            continue
        entries = TypeAdapter(list[DockerPlayerInspection]).validate_json(result.stdout)
        if len(entries) != 1:
            raise ValueError(f"Expected one player container inspection for seat {slot}")
        inspection = entries[0]
        receipts.append(LocalPlayerReceipt(slot=slot, container_name=name, inspection=inspection))
        state = inspection.state
        if state.running:
            statuses[slot] = PlayerRuntimeStatus(slot=slot, state="running", reason="runner_cleanup_pending")
        elif state.status in {"exited", "dead"}:
            statuses[slot] = PlayerRuntimeStatus(
                slot=slot,
                state="exited",
                exit_code=state.exit_code,
                reason="OOMKilled" if state.oom_killed else state.error or state.status,
                finished_at=TypeAdapter(datetime).validate_python(state.finished_at),
            )
        elif state.status == "created":
            statuses[slot] = PlayerRuntimeStatus(slot=slot, state="not_started", reason="container_created")
        else:
            statuses[slot] = PlayerRuntimeStatus(slot=slot, state="unavailable", reason=state.status)
    for name, payload in [
        ("player_status.json", PlayerRuntimeStatuses(players=statuses).model_dump_json(indent=2)),
        ("player_containers.json", LocalPlayerReceipts(players=receipts).model_dump_json(indent=2)),
    ]:
        fd = os.open(workspace / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as output:
            output.write(payload)
