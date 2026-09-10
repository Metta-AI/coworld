from __future__ import annotations

import time
from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

PHASE_GAME_BOOT = "game_boot"
PHASE_PLAYER_LAUNCH = "player_launch"
PHASE_FIRST_STEP = "first_step"
PHASE_GAMEPLAY = "gameplay"
PHASE_ARTIFACT_UPLOAD = "artifact_upload"


TimingOperation = Literal[
    "imports",
    "bootstrap",
    "spec_fetch",
    "spec_validate",
    "config_write",
    "player_files",
    "setup",
    "health_wait",
    "player_launch",
    "viewer_wait",
    "player_startup_wait",
    "artifact_wait",
    "results_validate",
    "players_complete",
    "logs_collect",
    "children_delete",
    "artifact_server_shutdown",
    "artifact_upload",
]


_MAX_TIMING_INT = 2**63 - 1


class TimingClock(BaseModel):
    """Bracketed wall/monotonic anchor; durations never use the wall clock."""

    wall_ns: int = Field(gt=0, le=_MAX_TIMING_INT)
    monotonic_ns: int = Field(ge=0, le=_MAX_TIMING_INT)
    uncertainty_ns: int = Field(ge=0, le=_MAX_TIMING_INT)

    @classmethod
    def capture(cls) -> Self:
        before = time.monotonic_ns()
        wall = time.time_ns()
        after = time.monotonic_ns()
        return cls(wall_ns=wall, monotonic_ns=(before + after) // 2, uncertainty_ns=after - before)


class TimingInterval(BaseModel):
    """Offsets from one producer's monotonic anchor, in nanoseconds."""

    start_ns: int = Field(ge=-_MAX_TIMING_INT, le=_MAX_TIMING_INT)
    end_ns: int = Field(ge=-_MAX_TIMING_INT, le=_MAX_TIMING_INT)

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.end_ns < self.start_ns:
            raise ValueError("timing interval ends before it starts")
        return self

    @property
    def seconds(self) -> float:
        return (self.end_ns - self.start_ns) / 1_000_000_000


class PlayerStartupTiming(BaseModel):
    pod_uid: str = Field(min_length=1, max_length=128)
    create: TimingInterval | None = None
    container_started_wall_ns: int | None = Field(default=None, ge=-_MAX_TIMING_INT, le=_MAX_TIMING_INT)
    observed_offset_ns: int | None = Field(default=None, ge=-_MAX_TIMING_INT, le=_MAX_TIMING_INT)
    outcome: Literal["started", "dead"] | None = None

    @model_validator(mode="after")
    def observed_after_create(self) -> Self:
        if (
            self.create is not None
            and self.observed_offset_ns is not None
            and self.observed_offset_ns < self.create.end_ns
        ):
            raise ValueError("player observation precedes pod creation")
        return self


class ProcessTimings(BaseModel):
    clock: TimingClock
    final_clock: TimingClock | None = None
    intervals: dict[TimingOperation, TimingInterval] = Field(default_factory=dict, max_length=32)
    players: dict[int, PlayerStartupTiming] = Field(default_factory=dict, max_length=1024)
    game_container_started_wall_ns: int | None = Field(default=None, ge=-_MAX_TIMING_INT, le=_MAX_TIMING_INT)
    process_birth_offset_ns: int | None = Field(default=None, ge=-_MAX_TIMING_INT, le=_MAX_TIMING_INT)
    process_birth_resolution_ns: int | None = Field(default=None, gt=0, le=_MAX_TIMING_INT)
    spec_bytes: int | None = Field(default=None, ge=0, le=_MAX_TIMING_INT)
    spec_scheme: str | None = Field(default=None, max_length=16)

    def record(self, operation: TimingOperation, start_ns: int, end_ns: int | None = None) -> float:
        interval = TimingInterval(
            start_ns=start_ns - self.clock.monotonic_ns,
            end_ns=(time.monotonic_ns() if end_ns is None else end_ns) - self.clock.monotonic_ns,
        )
        self.intervals[operation] = interval
        return interval.seconds


class PlayerFileStageTiming(BaseModel):
    stage_s: float = Field(ge=0, le=_MAX_TIMING_INT)
    count: int = Field(ge=0, le=_MAX_TIMING_INT)
    bytes_total: int = Field(ge=0, le=_MAX_TIMING_INT)


class EpisodePhaseTimings(BaseModel):
    """Worker-observed durations and explicit producer-local intervals.

    Health observation, viewer consumption, and artifact detection are not the
    game's own boot, first turn, or final turn. Incomplete intervals are omitted.
    Spans use explicit offsets; durations remain available for phase metrics.
    """

    worker: ProcessTimings | None = None
    init: ProcessTimings | None = None

    game_boot_s: float | None = None
    player_launch_s: float | None = None
    first_step_s: float | None = None
    gameplay_s: float | None = None
    artifact_upload_s: float | None = None
    player_file_stage: PlayerFileStageTiming | None = None
    slot_log_missing_count: int | None = Field(default=None, ge=0, le=_MAX_TIMING_INT)
    player_status_invalid_count: int | None = Field(default=None, ge=0, le=_MAX_TIMING_INT)
    player_artifact_oversize_count: int | None = Field(default=None, ge=0, le=_MAX_TIMING_INT)

    def phase_seconds(self) -> dict[str, float]:
        phases = {
            PHASE_GAME_BOOT: self.game_boot_s,
            PHASE_PLAYER_LAUNCH: self.player_launch_s,
            PHASE_FIRST_STEP: self.first_step_s,
            PHASE_GAMEPLAY: self.gameplay_s,
            PHASE_ARTIFACT_UPLOAD: self.artifact_upload_s,
        }
        return {phase: seconds for phase, seconds in phases.items() if seconds is not None}
