from copy import deepcopy
from types import SimpleNamespace

import pytest
from kubernetes.client.rest import ApiException

from coworld.runner import player_pod_launch_gate as gate_module
from coworld.runner.player_pod_launch_gate import PlayerPodLaunchGate


@pytest.fixture
def cluster(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(gate_module.time, "time", lambda: clock[0])
    lease = SimpleNamespace(metadata=SimpleNamespace(annotations={}, resource_version="0"))
    jobs = {}
    writes = []

    def replace(*, body, **_kwargs):
        assert body.metadata.resource_version == lease.metadata.resource_version
        lease.metadata.annotations = deepcopy(body.metadata.annotations)
        lease.metadata.resource_version = str(int(lease.metadata.resource_version) + 1)
        writes.append(deepcopy(body))

    coordination = SimpleNamespace(
        read_namespaced_lease=lambda **_kwargs: deepcopy(lease),
        replace_namespaced_lease=replace,
    )
    batch = SimpleNamespace(
        list_namespaced_job=lambda *, field_selector, **_kwargs: SimpleNamespace(
            items=[job for name, job in jobs.items() if field_selector == f"metadata.name={name}"]
        )
    )

    def gate(name, *, burst=2.0):
        jobs[name] = SimpleNamespace(
            metadata=SimpleNamespace(uid=f"{name}-uid", deletion_timestamp=None),
            status=SimpleNamespace(conditions=None),
        )
        return PlayerPodLaunchGate(
            coordination, batch, "jobs", job_name=name, job_uid=f"{name}-uid", refill_per_second=1.0, burst=burst
        )

    return SimpleNamespace(clock=clock, lease=lease, jobs=jobs, gate=gate, coordination=coordination, writes=writes)


@pytest.mark.parametrize("failure", ["deleted", "deleting", "failed", "complete", "replaced", "expired"])
def test_reclaims_only_unconsumed_slots_without_failed_owner(cluster, failure):
    first, second = cluster.gate("first"), cluster.gate("second")
    assert first.acquire(4).granted
    assert not second.acquire(2).granted
    if failure == "deleted":
        del cluster.jobs["first"]
    elif failure == "deleting":
        cluster.jobs["first"].metadata.deletion_timestamp = "now"
    elif failure == "replaced":
        cluster.jobs["first"].metadata.uid = "replacement-uid"
    elif failure == "expired":
        cluster.clock[0] += gate_module.RESERVATION_TTL_SECONDS
    else:
        cluster.jobs["first"].status.conditions = [
            SimpleNamespace(type="Failed" if failure == "failed" else "Complete", status="True")
        ]

    assert second.acquire(2).granted
    # The first worker's consumed token is never refunded by cleanup.
    if failure != "expired":
        assert not second.acquire(1).granted
        cluster.clock[0] += 1
    assert second.acquire(1).granted


def test_release_is_idempotent_and_does_not_refund_spent_tokens(cluster):
    first, second = cluster.gate("first"), cluster.gate("second")
    assert first.acquire(4).granted
    assert not second.acquire(2).granted
    first.release()
    first.release()
    assert second.acquire(2).granted
    assert not second.acquire(1).granted


def test_dead_owner_cannot_reacquire_and_multiple_abandoned_heads_are_reclaimed(cluster):
    first, second, third = cluster.gate("first"), cluster.gate("second"), cluster.gate("third")
    assert first.acquire(4).granted
    assert not second.acquire(2).granted
    assert not third.acquire(1).granted
    del cluster.jobs["first"]
    del cluster.jobs["second"]
    with pytest.raises(RuntimeError, match="no longer active"):
        first.acquire(3)
    assert third.acquire(1).granted


def test_expired_owner_reacquires_behind_live_owner(cluster):
    first, second = cluster.gate("first"), cluster.gate("second")
    assert first.acquire(4).granted
    assert not second.acquire(4).granted
    cluster.clock[0] += gate_module.RESERVATION_TTL_SECONDS / 2
    assert not second.acquire(4).granted  # renew while the head is still alive
    cluster.clock[0] += gate_module.RESERVATION_TTL_SECONDS / 2
    assert second.acquire(4).granted  # expired head no longer owns its old slots
    assert not first.acquire(3).granted  # resumed worker must queue behind second
    second.release()
    assert first.acquire(3).granted
    assert not first.acquire(2).granted


def test_live_owner_renews_through_long_launch_wait(cluster):
    first, second = cluster.gate("first", burst=1.0), cluster.gate("second", burst=1.0)
    assert first.acquire(5000).granted
    remaining = 4999
    for _ in range(100):
        assert not second.acquire(1).granted
        cluster.clock[0] += gate_module.RESERVATION_TTL_SECONDS / 2
        assert first.acquire(remaining).granted
        remaining -= 1
    assert not second.acquire(1).granted


def test_oversized_roster_obeys_burst_and_refill(cluster):
    first = cluster.gate("first")
    assert first.acquire(4).granted
    assert first.acquire(3).granted
    decision = first.acquire(2)
    assert not decision.granted
    assert decision.finish_delay == 2.0
    assert decision.retry_after == 1.0
    cluster.clock[0] += 1
    assert first.acquire(2).granted
    assert not first.acquire(1).granted
    cluster.clock[0] += 1
    assert first.acquire(1).granted


def test_clock_never_regresses_or_refills_twice(cluster):
    first = cluster.gate("first", burst=1.0)
    assert first.acquire(3).granted
    cluster.clock[0] = 99.0
    assert not first.acquire(2).granted
    cluster.clock[0] = 100.0
    assert not first.acquire(2).granted
    cluster.clock[0] = 101.0
    assert first.acquire(2).granted
    assert not first.acquire(1).granted


def test_conflict_rereads_state_and_does_not_grant_twice(cluster):
    first, competitor = cluster.gate("first", burst=1.0), cluster.gate("competitor", burst=1.0)
    replace = cluster.coordination.replace_namespaced_lease

    def conflict(**kwargs):
        cluster.coordination.replace_namespaced_lease = replace
        assert competitor.acquire(1).granted
        raise ApiException(status=409)

    cluster.coordination.replace_namespaced_lease = conflict
    assert not first.acquire(1).granted
    assert len(cluster.writes) == 2


def test_prolonged_conflicts_return_to_launch_wait_loop(cluster, monkeypatch):
    worker = cluster.gate("worker")
    replace = cluster.coordination.replace_namespaced_lease
    monkeypatch.setattr(gate_module.time, "monotonic", lambda: cluster.clock[0])
    monkeypatch.setattr(gate_module.time, "sleep", lambda _: None)

    def conflict(**_kwargs):
        cluster.clock[0] += 5
        raise ApiException(status=409)

    cluster.coordination.replace_namespaced_lease = conflict
    for _ in range(12):
        decision = worker.acquire(2)
        assert not decision.granted
        assert decision.retry_after > 0
    assert cluster.clock[0] >= 160
    assert not cluster.writes

    cluster.coordination.replace_namespaced_lease = replace
    assert worker.acquire(2).granted
    assert worker.acquire(1).granted
    assert not worker.acquire(1).granted


def test_release_retries_conflicts_past_thirty_seconds(cluster, monkeypatch):
    worker = cluster.gate("worker")
    assert worker.acquire(2).granted
    replace = cluster.coordination.replace_namespaced_lease
    monkeypatch.setattr(gate_module.time, "monotonic", lambda: cluster.clock[0])
    monkeypatch.setattr(gate_module.time, "sleep", lambda _: None)
    conflicts = 0

    def conflict(**kwargs):
        nonlocal conflicts
        if conflicts < 35:
            conflicts += 1
            cluster.clock[0] += 1
            raise ApiException(status=409)
        replace(**kwargs)

    cluster.coordination.replace_namespaced_lease = conflict
    worker.release()
    assert conflicts == 35
    state = gate_module.LaunchState.model_validate_json(
        cluster.lease.metadata.annotations[gate_module.LAUNCH_STATE_ANNOTATION]
    )
    assert not state.reservations


@pytest.mark.parametrize("status", [403, 500])
@pytest.mark.parametrize("operation", ["acquire", "release"])
def test_non_conflict_api_errors_propagate(cluster, status, operation):
    worker = cluster.gate("worker")

    def failure(**_kwargs):
        raise ApiException(status=status)

    cluster.coordination.replace_namespaced_lease = failure
    with pytest.raises(ApiException) as raised:
        if operation == "acquire":
            worker.acquire(1)
        else:
            worker.release()
    assert raised.value.status == status
