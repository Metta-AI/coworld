"""Shared resource contracts for the dispatcher and trusted runner entrypoints, plus process timings."""

import os
import sys
import time
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit

from pydantic import ValidationError

from coworld.runner.io import (
    RunnerEpisodeError,
    RunnerError,
    RunnerErrorType,
    exception_summary,
    is_retryable_relay_error,
    read_data,
    upload_data,
)
from coworld.runner.phase_timings import ProcessTimings, TimingClock
from coworld.types import CoworldEpisodeJobSpec

WORKDIR = Path(os.environ.get("COWORLD_WORKDIR", "/coworld"))
STATE_PATH = WORKDIR / "state.json"
COORDINATOR_SPEC_PATH = Path("/var/run/coworld-coordinator/job_spec.json")


def process_timings(
    *, import_start_ns: int, import_wall_ns: int, import_anchor_end_ns: int, import_done_ns: int
) -> ProcessTimings:
    clock = TimingClock(
        wall_ns=import_wall_ns,
        monotonic_ns=(import_start_ns + import_anchor_end_ns) // 2,
        uncertainty_ns=import_anchor_end_ns - import_start_ns,
    )
    timings = ProcessTimings(clock=clock)
    timings.record("imports", import_start_ns, import_done_ns)
    if sys.platform == "linux":
        # /proc starttime is ticks since boot; align via CLOCK_BOOTTIME, not wall time.
        ticks = os.sysconf("SC_CLK_TCK")
        start_ticks = int(Path("/proc/self/stat").read_text().rsplit(") ", 1)[1].split()[19])
        boot_ns = time.clock_gettime_ns(time.CLOCK_BOOTTIME)
        monotonic_ns = time.monotonic_ns()
        timings.process_birth_offset_ns = (
            start_ticks * 1_000_000_000 // ticks - boot_ns + monotonic_ns - clock.monotonic_ns
        )
        timings.process_birth_resolution_ns = 1_000_000_000 // ticks
    return timings


def read_job_spec(timings: ProcessTimings) -> tuple[CoworldEpisodeJobSpec, bytes]:
    start = time.monotonic_ns()
    uri = os.environ["JOB_SPEC_URI"]
    raw = read_data(uri)
    fetched = time.monotonic_ns()
    job = CoworldEpisodeJobSpec.model_validate_json(raw)
    timings.record("spec_fetch", start, fetched)
    timings.record("spec_validate", fetched)
    timings.spec_bytes = len(raw)
    timings.spec_scheme = urlsplit(uri).scheme
    return job, raw


def write_error_info(exc: Exception, *, default_error_type: RunnerErrorType = "crash") -> None:
    error_info_uri = os.environ.get("ERROR_INFO_URI")
    if isinstance(exc, RunnerEpisodeError):
        runner_error = RunnerError(
            error_type=cast(RunnerErrorType, exc.error_type),
            message=str(exc)[:2000],
            failed_policy_index=exc.failed_policy_index,
        )
    elif is_retryable_relay_error(exc):
        runner_error = RunnerError(error_type="artifact_transport_error", message=exception_summary(exc))
    elif isinstance(exc, ValidationError):
        runner_error = RunnerError(
            error_type="config_error", message=str(exc.errors(include_input=False, include_context=False))[:2000]
        )
    else:
        runner_error = RunnerError(error_type=default_error_type, message=exception_summary(exc))
    error_type_path = os.environ.get("COWORLD_ERROR_TYPE_PATH")
    if error_type_path is not None:
        Path(error_type_path).write_text(runner_error.error_type, encoding="utf-8")
    if error_info_uri is not None:
        upload_data(error_info_uri, runner_error.model_dump_json(), content_type="application/json")
