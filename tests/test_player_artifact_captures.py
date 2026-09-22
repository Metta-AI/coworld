import hashlib
import json
import threading
import time
from datetime import UTC, datetime, timedelta
from http.client import RemoteDisconnected
from io import BytesIO
from unittest.mock import MagicMock
from urllib.request import Request, urlopen
from uuid import uuid4

import httpx
import pytest

from coworld.runner import kubernetes_runner
from coworld.runner import player_artifacts as artifacts


@pytest.fixture
def upload(monkeypatch, tmp_path):
    session = artifacts.PersistentDiagnosticSession(
        runtime_id=uuid4(),
        session_id=uuid4(),
        player_id=f"ply_{uuid4()}",
        policy_version_id=uuid4(),
        coworld_id=f"cow_{uuid4()}",
        generation=1,
        created_at=datetime.now(UTC),
    )
    capture = artifacts.PlayerArtifactCapture(
        capture_id=uuid4(),
        started_at=session.created_at,
        ended_at=session.created_at + timedelta(minutes=1),
    )
    client = MagicMock()
    client.__enter__.return_value = client
    monkeypatch.setenv("COWORLD_EGRESS_RELAY_URL", "http://relay.test:3128")
    monkeypatch.setattr(artifacts, "relay_http_client", lambda _: client)
    return dict(
        grant=artifacts.PlayerArtifactUploadGrant(url="https://storage.example", fields={"policy": "signed"}),
        session=session,
        capture=capture,
        artifact=BytesIO(b"zip"),
        size=3,
        ledger_path=tmp_path / "ledger.json",
    ), client


def test_content_addressed_retry_reuses_identity_and_budget(upload):
    args, client = upload
    first = artifacts.upload_captured_player_artifact(**args)
    second = artifacts.upload_captured_player_artifact(**args)
    assert first is not None
    assert first == second
    assert first.sha256 == hashlib.sha256(b"zip").hexdigest()
    assert json.loads(args["ledger_path"].read_text()) == {first.reference.artifact_id: 3}
    assert client.post.call_count == 4
    assert client.post.call_args_list[0].kwargs["data"]["key"] == f"{first.reference.prefix}/artifact.zip"
    assert client.post.call_args_list[1].kwargs["files"]["file"][1] == first.canonical_bytes()
    changed = artifacts.upload_captured_player_artifact(**{**args, "artifact": BytesIO(b"new")})
    assert changed is not None
    assert changed.reference != first.reference


@pytest.mark.parametrize("budget", ["count", "bytes"])
def test_session_budget_survives_reopening_ledger_and_allows_identical_retry(upload, monkeypatch, budget):
    args, client = upload
    monkeypatch.setattr(artifacts, "PLAYER_ARTIFACT_SESSION_MAX_COUNT", 1 if budget == "count" else 128)
    monkeypatch.setattr(artifacts, "PLAYER_ARTIFACT_SESSION_MAX_BYTES", 3 if budget == "bytes" else 512 * 1024 * 1024)
    first = artifacts.upload_captured_player_artifact(**args)
    assert artifacts.upload_captured_player_artifact(**{**args, "artifact": BytesIO(b"new")}) is None
    assert client.post.call_count == 2
    assert artifacts.upload_captured_player_artifact(**args) == first


def test_failed_upload_still_consumes_reservation(upload):
    args, client = upload
    client.post.side_effect = RuntimeError("upload failed")
    with pytest.raises(RuntimeError, match="upload failed"):
        artifacts.upload_captured_player_artifact(**args)
    assert sum(json.loads(args["ledger_path"].read_text()).values()) == 3


def test_capture_requires_ordered_timezone_aware_bounds():
    with pytest.raises(ValueError):
        artifacts.PlayerArtifactCapture.model_validate(
            {"capture_id": str(uuid4()), "started_at": "2026-09-01T00:00:00", "ended_at": "2026-09-01T00:01:00Z"}
        )
    with pytest.raises(ValueError):
        artifacts.PlayerArtifactCapture.model_validate(
            {"capture_id": str(uuid4()), "started_at": "2026-09-01T00:02:00Z", "ended_at": "2026-09-01T00:01:00Z"}
        )


@pytest.mark.parametrize("failure", ["503", "timeout"])
def test_failed_retained_capture_does_not_block_next_live_upload(upload, monkeypatch, tmp_path, failure):
    args, storage = upload
    request = httpx.Request("POST", args["grant"].url)
    storage.post.side_effect = (
        httpx.HTTPStatusError("storage unavailable", request=request, response=httpx.Response(503, request=request))
        if failure == "503"
        else httpx.ReadTimeout("storage timed out", request=request)
    )
    targets = artifacts.PersistentDiagnosticTargets(
        session=args["session"],
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        targets={"0": "https://storage.example/live"},
        artifact_upload=args["grant"],
    )
    target_path = tmp_path / "targets.json"
    target_path.write_text(targets.model_dump_json())
    monkeypatch.setenv("PLAYER_ARTIFACT_UPLOAD_URLS", f"file://{target_path}")
    monkeypatch.setattr(kubernetes_runner, "WORKDIR", tmp_path)
    monkeypatch.setattr(kubernetes_runner, "PLAYER_ARTIFACT_PORT", 0)
    live_uploads = []

    def upload_live(uri, stream, **_kwargs):
        stream.seek(0)
        live_uploads.append((uri, stream.read()))

    monkeypatch.setattr(kubernetes_runner, "upload_file", upload_live)
    server = kubernetes_runner._PlayerArtifactUploadServer(targets={0: targets.targets["0"]}, tokens=["secret"])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}/player-artifact/0/secret"
    try:
        with pytest.raises(RemoteDisconnected):
            urlopen(
                Request(
                    url,
                    data=b"capture",
                    method="PUT",
                    headers={
                        artifacts.PLAYER_ARTIFACT_CAPTURE_HEADER: args["capture"].model_dump_json(),
                    },
                ),
                timeout=2,
            )
        deadline = time.monotonic() + 2
        while server.active_connections:
            assert time.monotonic() < deadline
            time.sleep(0.01)
        assert not server.inflight_slots
        with urlopen(Request(url, data=b"new live snapshot", method="PUT"), timeout=2) as response:
            assert response.status == 201
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    assert live_uploads == [(targets.targets["0"], b"new live snapshot")]
    assert storage.post.call_count == 1
