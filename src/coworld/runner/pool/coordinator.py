"""Reusable assignment owner; episode subprocesses retain the existing runner contract."""

import os
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import UUID

import httpx
from pydantic import BaseModel, Field, TypeAdapter
from tenacity import retry, retry_if_exception_type, stop_after_delay, wait_exponential

from coworld.runner.io import RunnerError, upload_data
from coworld.runner.player_artifacts import ARTIFACT_TARGETS_PATH
from coworld.runner.pool.control import CONTROL_DIR, GAME_UID, control
from coworld.runner.pool.types import ExecutionProfile, PoolArtifactTargets, PreparedPoolEpisode

WORKDIR = Path("/coworld")
PRIVATE = Path("/var/run/coworld-coordinator")
TMPDIR = Path("/pool-tmp")
SHMDIR = Path("/pool-shm")


class Assignment(BaseModel):
    kind: Literal["assignment"]
    job_id: UUID
    attempt_id: UUID
    prepared: PreparedPoolEpisode
    heartbeat_interval_seconds: int = Field(gt=0)
    lease_expires_at: datetime


class Wait(BaseModel):
    kind: Literal["wait"]
    retry_after_seconds: int = Field(ge=0)


class Retired(BaseModel):
    kind: Literal["retired"]


CLAIM_RESPONSE = TypeAdapter(Annotated[Assignment | Wait | Retired, Field(discriminator="kind")])


class Heartbeat(BaseModel):
    stop: bool
    lease_expires_at: datetime | None


class PoolClient:
    def __init__(self, endpoint: str, token: str) -> None:
        self.http = httpx.Client(
            base_url=endpoint.rstrip("/") + "/v2/experience-episodes/",
            headers={"Authorization": f"Bearer {token}"},
            timeout=5,
            transport=httpx.HTTPTransport(retries=2),
        )

    @retry(
        retry=retry_if_exception_type(httpx.TransportError),
        wait=wait_exponential(min=0.2, max=2),
        stop=stop_after_delay(10),
        reraise=True,
    )
    def post(self, operation: str, body: dict[str, Any]) -> httpx.Response:
        response = self.http.post(
            operation,
            json=body,
            params={"wait_seconds": 15} if operation == "claim" else None,
            timeout=20 if operation == "claim" else 5,
        )
        response.raise_for_status()
        return response


def _wait_child(
    child: subprocess.Popen[bytes],
    client: PoolClient,
    assignment: Assignment,
    *,
    running_at: datetime | None,
    deadline: float,
    targets: PoolArtifactTargets,
) -> bool:
    lease_deadline = assignment.lease_expires_at
    while child.poll() is None:
        assert datetime.now(UTC) < lease_deadline, "Assignment lease expired"
        assert time.monotonic() < deadline, "Episode process exceeded its deadline"
        control("", 0)
        if (targets.uploads.expires_at - datetime.now(UTC)).total_seconds() < 3600:
            refreshed = PoolArtifactTargets.model_validate_json(
                client.post(
                    "artifacts",
                    {
                        "job_id": str(assignment.job_id),
                        "attempt_id": str(assignment.attempt_id),
                    },
                ).content
            )
            targets.uploads = refreshed.uploads
            _write_upload_targets(targets)
        heartbeat = Heartbeat.model_validate_json(
            client.post(
                "heartbeat",
                {
                    "job_id": str(assignment.job_id),
                    "attempt_id": str(assignment.attempt_id),
                    "running_at": running_at.isoformat() if running_at else None,
                },
            ).content
        )
        if heartbeat.stop:
            child.terminate()
            child.wait(timeout=10)
            return False
        assert heartbeat.lease_expires_at is not None
        lease_deadline = heartbeat.lease_expires_at
        assignment.lease_expires_at = lease_deadline
        # Polling is interruptible by child exit; heartbeat cadence is independent of episode length.
        until = time.monotonic() + assignment.heartbeat_interval_seconds
        while child.poll() is None and time.monotonic() < until:
            time.sleep(0.1)
    return True


def _clear_directory(directory: Path) -> None:
    for path in directory.iterdir():
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()


def _write_upload_targets(targets: PoolArtifactTargets) -> None:
    destination = Path(ARTIFACT_TARGETS_PATH)
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(targets.uploads.model_dump_json())
    temporary.replace(destination)


def run_assignment(client: PoolClient, assignment: Assignment, profile: ExecutionProfile) -> None:
    prepared = assignment.prepared
    assert prepared.profile.content_hash() == profile.content_hash(), "Incompatible assignment"
    identity = {"job_id": str(assignment.job_id), "attempt_id": str(assignment.attempt_id)}
    key = str(assignment.attempt_id)
    targets = PoolArtifactTargets.model_validate_json(client.post("artifacts", identity).content)
    _write_upload_targets(targets)
    _clear_directory(PRIVATE)
    (PRIVATE / "input.json").write_text(targets.spec.model_dump_json())
    game_env = {
        **targets.game_env,
        "COGAME_HOST": "0.0.0.0",
        "COGAME_PORT": "8080",
        "COGAME_CONFIG_URI": "file:///coworld/config.json",
        "COGAME_RESULTS_URI": "file:///coworld/results.json",
        "COGAME_SAVE_REPLAY_URI": "file:///coworld/replay",
        "COGAME_SAVE_TRAJECTORY_URI": "file:///coworld/trajectory.jsonl",
        "COGAME_EVENTS_URI": "file:///coworld/events.json",
        "COGAME_PLAYER_FAILURE_URI": "file:///coworld/player_failure.json",
        "COGAME_PLAYER_SEATS_URI": "file:///coworld/player_seats.json",
    }
    # Platform credentials stay in the parent. Each trusted child receives assignment-only capabilities.
    env = {
        "PATH": os.environ["PATH"],
        **targets.coordinator_env,
        **{key: value for key, value in game_env.items() if key.startswith("COGAME_")},
        "JOB_SPEC_URI": (PRIVATE / "input.json").as_uri(),
        "COWORLD_WORKDIR": str(WORKDIR),
        "COWORLD_TIMEOUT_SECONDS": str(prepared.timeout_seconds),
        "COWORLD_ERROR_INFO_PATH": str(PRIVATE / "error-info.json"),
        "COWORLD_POOL_ASSIGNMENT": key,
        "XP_POOL_CACHE_DIR": os.environ["XP_POOL_CACHE_DIR"],
        "XP_POOL_CACHE_MAX_BYTES": os.environ["XP_POOL_CACHE_MAX_BYTES"],
    }
    # Initialization writes fixed paths before untrusted code can create files or links.
    _clear_directory(WORKDIR)
    _clear_directory(TMPDIR)
    _clear_directory(SHMDIR)
    child = subprocess.Popen([sys.executable, "-m", "coworld.runner.init_config"], env=env)
    launched = False
    try:
        active = _wait_child(
            child, client, assignment, running_at=None, deadline=time.monotonic() + 300, targets=targets
        )
        if not active:
            return
        if child.returncode == 0:
            for path in (WORKDIR, *WORKDIR.rglob("*"), TMPDIR, SHMDIR):
                os.chown(path, GAME_UID, GAME_UID, follow_symlinks=False)
            control(
                key,
                1,
                command=profile.command,
                env=game_env,
                cwd=profile.image.working_directory,
                timeout_seconds=prepared.timeout_seconds,
            )
            launched = True
            running_at = datetime.now(UTC)
            heartbeat = Heartbeat.model_validate_json(
                client.post(
                    "heartbeat",
                    {
                        **identity,
                        "running_at": running_at.isoformat(),
                    },
                ).content
            )
            if heartbeat.stop:
                return
            assert heartbeat.lease_expires_at is not None
            assignment.lease_expires_at = heartbeat.lease_expires_at
            env["JOB_SPEC_URI"] = (PRIVATE / "job_spec.json").as_uri()
            child = subprocess.Popen(
                [sys.executable, "-m", "coworld.runner.kubernetes_runner", "run-core-sidecars-v1"], env=env
            )
            active = _wait_child(
                child,
                client,
                assignment,
                running_at=running_at,
                deadline=time.monotonic() + prepared.timeout_seconds + 120,
                targets=targets,
            )
            if not active:
                return
        outcome: dict[str, Any]
        if child.returncode == 0:
            outcome = {"status": "completed", **targets.completion.model_dump()}
        else:
            error_info_path = PRIVATE / "error-info.json"
            if error_info_path.exists():
                runner_error = RunnerError.model_validate_json(error_info_path.read_text())
                outcome = {
                    "status": "failed",
                    "error": runner_error.message,
                    "error_type": runner_error.error_type,
                    "result": (
                        {"failed_policy_index": runner_error.failed_policy_index}
                        if runner_error.failed_policy_index is not None
                        else {}
                    ),
                }
            else:
                outcome = {
                    "status": "failed",
                    "error": f"Episode coordinator exited with code {child.returncode}",
                    "error_type": "worker_error",
                }
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)
        if launched:
            status = control(key, 3)
            assert status.state == 3, "Game cleanup was not confirmed"
        try:
            if launched:
                # The Pod log spans many episodes. Publish only this process's streams.
                with (CONTROL_DIR / "stdout").open("rb") as stdout, (CONTROL_DIR / "stderr").open("rb") as stderr:
                    logs = stdout.read(1024 * 1024) + stderr.read(1024 * 1024)
                upload_data(targets.uploads.targets["logs.txt"], logs, content_type="text/plain")
        finally:
            _clear_directory(WORKDIR)
            _clear_directory(TMPDIR)
            _clear_directory(SHMDIR)
            _clear_directory(PRIVATE)
            Path(ARTIFACT_TARGETS_PATH).unlink()
            for log in ("stdout", "stderr"):
                (CONTROL_DIR / log).unlink(missing_ok=True)
    # The worker becomes claimable only after outputs are durable and all episode state is gone.
    client.post("complete", {**identity, "outcome": outcome})


def main() -> None:
    profile = ExecutionProfile.model_validate_json(Path(os.environ["XP_POOL_PROFILE_PATH"]).read_bytes())
    client = PoolClient(os.environ["XP_POOL_API_URL"], Path(os.environ["XP_POOL_TOKEN_PATH"]).read_text().strip())
    max_age_seconds = int(os.environ["XP_POOL_MAX_AGE_SECONDS"])
    started = time.monotonic()
    episodes = 0
    last_assignment = started
    try:
        startup_deadline = time.monotonic() + 60
        while not (CONTROL_DIR / "control.sock").exists():
            assert time.monotonic() < startup_deadline, "Supervisor did not start"
            time.sleep(0.1)
        # A restarted coordinator cannot prove publication/cleanup of an earlier process.
        assert control("", 0).state == 0, "Supervisor has prior execution state; retire for recovery"
        # Retire unused capacity while keeping preparation independent of supervisor idle expiry.
        while (
            episodes < 50 and time.monotonic() - started < max_age_seconds and time.monotonic() - last_assignment < 540
        ):
            control("", 0)
            response = CLAIM_RESPONSE.validate_json(client.post("claim", {}).content)
            if isinstance(response, Retired):
                return
            if isinstance(response, Wait):
                time.sleep(response.retry_after_seconds)
                continue
            run_assignment(client, response, profile)
            episodes += 1
            last_assignment = time.monotonic()
    finally:
        client.post("retire", {})
        client.http.close()


if __name__ == "__main__":
    main()
