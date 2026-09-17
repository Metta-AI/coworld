from __future__ import annotations

import time
from typing import cast

from kubernetes import client
from kubernetes.client.rest import ApiException
from pydantic import BaseModel, Field
from tenacity import Retrying, retry_if_exception, stop_after_delay, stop_never, wait_random_exponential

from coworld.runner.bootstrap import LAUNCH_LEASE

LAUNCH_STATE_ANNOTATION = "softmax.com/player-pod-launch-state"
RESERVATION_TTL_SECONDS = 60.0
LAUNCH_POLL_SECONDS = 5.0


class LaunchReservation(BaseModel):
    job_name: str
    job_uid: str
    remaining: int = Field(gt=0)
    expires_at: float


class LaunchState(BaseModel):
    tokens: float = Field(ge=0)
    refilled_at: float
    reservations: list[LaunchReservation] = Field(default_factory=list)


class LaunchDecision(BaseModel):
    granted: bool
    finish_delay: float
    retry_after: float = LAUNCH_POLL_SECONDS


class PlayerPodLaunchGate:
    """FIFO reservations; only an immediately consumed slot spends a bucket token.

    Every mutation is fenced by the Lease resourceVersion. Expired owners rejoin
    the tail, so a paused worker cannot spend slots another worker reclaimed.
    """

    def __init__(
        self,
        coordination: client.CoordinationV1Api,
        batch: client.BatchV1Api,
        namespace: str,
        *,
        job_name: str,
        job_uid: str,
        refill_per_second: float,
        burst: float,
    ) -> None:
        assert refill_per_second > 0
        assert burst >= 1
        self.coordination = coordination
        self.batch = batch
        self.namespace = namespace
        self.job_name = job_name
        self.job_uid = job_uid
        self.refill_per_second = refill_per_second
        self.burst = burst

    def acquire(self, remaining: int) -> LaunchDecision:
        assert remaining > 0
        return self._update(remaining)

    def release(self) -> None:
        self._update(0)

    def _update(self, remaining: int) -> LaunchDecision:
        for attempt in Retrying(
            retry=retry_if_exception(lambda exc: isinstance(exc, ApiException) and exc.status == 409),
            # Yield acquisition conflicts to the launch loop so it can keep
            # extending the Job deadline. Cleanup retries until it commits.
            stop=stop_after_delay(1) if remaining else stop_never,
            wait=wait_random_exponential(multiplier=0.01, max=0.25),
            retry_error_callback=lambda _: None,
        ):
            with attempt:
                lease = cast(
                    client.V1Lease,
                    self.coordination.read_namespaced_lease(name=LAUNCH_LEASE, namespace=self.namespace),
                )
                metadata = cast(client.V1ObjectMeta, lease.metadata)
                annotations = dict(metadata.annotations or {})
                now = time.time()
                state = (
                    LaunchState.model_validate_json(annotations[LAUNCH_STATE_ANNOTATION])
                    if LAUNCH_STATE_ANNOTATION in annotations
                    else LaunchState(tokens=self.burst, refilled_at=now)
                )
                refill_time = max(now, state.refilled_at)
                state.tokens = min(
                    self.burst, state.tokens + (refill_time - state.refilled_at) * self.refill_per_second
                )
                state.refilled_at = refill_time
                state.reservations = [
                    reservation
                    for reservation in state.reservations
                    if reservation.expires_at > refill_time and (remaining > 0 or reservation.job_uid != self.job_uid)
                ]
                decision = LaunchDecision(granted=False, finish_delay=0)
                if remaining:
                    owned = next((entry for entry in state.reservations if entry.job_uid == self.job_uid), None)
                    if owned is None:
                        owned = LaunchReservation(
                            job_name=self.job_name,
                            job_uid=self.job_uid,
                            remaining=remaining,
                            expires_at=refill_time + RESERVATION_TTL_SECONDS,
                        )
                        state.reservations.append(owned)
                    assert owned.remaining == remaining, "worker and shared reservation progress disagree"
                    owned.expires_at = refill_time + RESERVATION_TTL_SECONDS

                    # Inspect only the queue head. A canceled tail cannot block a
                    # launch until it reaches the head; expired entries prune above.
                    while state.reservations:
                        head = state.reservations[0]
                        jobs = cast(
                            list[client.V1Job],
                            cast(
                                client.V1JobList,
                                self.batch.list_namespaced_job(
                                    namespace=self.namespace, field_selector=f"metadata.name={head.job_name}"
                                ),
                            ).items,
                        )
                        active = False
                        for job in jobs:
                            owner_metadata = cast(client.V1ObjectMeta, job.metadata)
                            owner_status = cast(client.V1JobStatus, job.status)
                            if (
                                owner_metadata.uid == head.job_uid
                                and owner_metadata.deletion_timestamp is None
                                and not any(
                                    condition.type in {"Complete", "Failed", "FailureTarget"}
                                    and condition.status == "True"
                                    for condition in (owner_status.conditions or [])
                                )
                            ):
                                active = True
                                break
                        if active:
                            break
                        state.reservations.pop(0)
                        if head.job_uid == self.job_uid:
                            raise RuntimeError("Coordinator Job is no longer active")

                    ahead = 0
                    for entry in state.reservations:
                        if entry.job_uid == self.job_uid:
                            break
                        ahead += entry.remaining
                    decision.finish_delay = (
                        refill_time - now + max(0.0, (ahead + remaining - state.tokens) / self.refill_per_second)
                    )
                    if state.reservations[0].job_uid == self.job_uid:
                        decision.retry_after = refill_time - now + max(0.0, (1 - state.tokens) / self.refill_per_second)
                        if state.tokens >= 1 and now >= refill_time:
                            state.tokens -= 1
                            owned.remaining -= 1
                            if owned.remaining == 0:
                                state.reservations.pop(0)
                            decision.granted = True

                annotations[LAUNCH_STATE_ANNOTATION] = state.model_dump_json()
                metadata.annotations = annotations
                self.coordination.replace_namespaced_lease(name=LAUNCH_LEASE, namespace=self.namespace, body=lease)
                return decision
        return LaunchDecision(granted=False, finish_delay=LAUNCH_POLL_SECONDS)
