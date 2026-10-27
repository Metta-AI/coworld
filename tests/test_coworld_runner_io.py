import asyncio
import logging
from io import BytesIO

import httpx
import pytest

from coworld.runner import io as runner_io


@pytest.mark.asyncio
async def test_upload_deadline_closes_stalled_connection(monkeypatch):
    monkeypatch.delenv("COWORLD_EGRESS_RELAY_URL", raising=False)
    closed = asyncio.Event()

    async def stall(reader, writer):
        try:
            await reader.read()
        finally:
            writer.close()
            await writer.wait_closed()
            closed.set()

    async with await asyncio.start_server(stall, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        with pytest.raises(TimeoutError):
            await runner_io.upload_data_with_deadline(
                f"http://127.0.0.1:{port}/timings", "{}", content_type="application/json", timeout_seconds=0.5
            )
        await asyncio.wait_for(closed.wait(), timeout=5)


class _RelayClient:
    def __init__(self, request):
        self._request = request

    def __enter__(self):
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        return None

    def get(self, uri: str):
        return self._request("GET", uri)

    def put(self, uri: str, **kwargs):
        return self._request("PUT", uri, **kwargs)


def test_relay_retry_log_redacts_presigned_url(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    calls = 0
    signed_url = "https://example.test/player?X-Amz-Signature=secret&X-Amz-Credential=credential"

    def request(method: str, uri: str):
        nonlocal calls
        calls += 1
        response = httpx.Response(503 if calls == 1 else 200, request=httpx.Request(method, uri), content=b"player")
        return response

    monkeypatch.setenv("COWORLD_EGRESS_RELAY_URL", "https://relay.test:3128")
    monkeypatch.setattr(runner_io, "_relay_http_client", lambda relay_url: _RelayClient(request))
    monkeypatch.setattr(runner_io.time, "sleep", lambda _delay: None)
    caplog.set_level(logging.WARNING, logger=runner_io.__name__)

    assert runner_io.read_data(signed_url) == b"player"
    assert "https://example.test/player" in caplog.text
    assert "X-Amz-" not in caplog.text


def test_upload_file_rejects_source_growth_beyond_declared_size(tmp_path) -> None:
    destination = tmp_path / "player.zip"

    with pytest.raises(ValueError, match="grew beyond its declared Content-Length"):
        runner_io.upload_file(
            destination.as_uri(),
            BytesIO(b"artifact bytes grew"),
            size=len(b"artifact bytes"),
            content_type="application/zip",
            attempts=1,
        )
