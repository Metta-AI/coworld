import logging
from datetime import UTC, datetime, timedelta
from email.message import Message
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError

import httpx
import pytest

from coworld.runner import io as runner_io
from coworld.runner import relay_client
from coworld.runner.player_artifacts import ArtifactUploadTargets


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        return None


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


def _http_error(url: str, code: int) -> HTTPError:
    return HTTPError(url, code, "error", hdrs=Message(), fp=None)


def _httpx_response(status_code: int, *, method: str = "PUT", content: bytes = b"") -> httpx.Response:
    return httpx.Response(
        status_code,
        content=content,
        request=httpx.Request(method, "https://example.test/data"),
    )


def test_upload_data_retries_transient_http_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    sleeps: list[float] = []

    def urlopen(request, *, timeout: int):
        calls.append((request, timeout))
        if len(calls) == 1:
            raise _http_error(request.full_url, 503)
        return _Response()

    monkeypatch.setattr(runner_io, "urlopen", urlopen)
    monkeypatch.setattr(runner_io.time, "sleep", sleeps.append)

    runner_io.upload_data("https://example.test/results.json", "{}", content_type="application/json")

    assert len(calls) == 2
    assert calls[0][0].get_method() == "PUT"
    assert sleeps == [0.5]


def test_upload_data_does_not_retry_client_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def urlopen(request, *, timeout: int):
        calls.append((request, timeout))
        raise _http_error(request.full_url, 400)

    monkeypatch.setattr(runner_io, "urlopen", urlopen)

    with pytest.raises(HTTPError):
        runner_io.upload_data("https://example.test/results.json", "{}", content_type="application/json")

    assert len(calls) == 1


def test_relay_routed_read_requires_https(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COWORLD_EGRESS_RELAY_URL", "https://relay.test:3128")

    with pytest.raises(ValueError, match="require an https URI"):
        runner_io.read_data("http://example.test/job.json")


def test_relay_routed_read_retries_transient_transport_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    sleeps: list[float] = []

    def request(method: str, uri: str):
        calls.append((method, uri))
        if len(calls) == 1:
            raise httpx.ConnectError("relay connection failed")
        return _httpx_response(200, method=method, content=b"job spec")

    monkeypatch.setenv("COWORLD_EGRESS_RELAY_URL", "https://relay.test:3128")
    monkeypatch.setattr(runner_io, "_relay_http_client", lambda relay_url: _RelayClient(request))
    monkeypatch.setattr(runner_io.time, "sleep", sleeps.append)

    assert runner_io.read_data("https://example.test/job.json") == b"job spec"
    assert calls == [
        ("GET", "https://example.test/job.json"),
        ("GET", "https://example.test/job.json"),
    ]
    assert sleeps == [0.5]


def test_relay_routed_read_retries_transient_statuses(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    sleeps: list[float] = []

    def request(method: str, uri: str):
        calls.append((method, uri))
        status_code = 503 if len(calls) == 1 else 200
        return _httpx_response(status_code, method=method, content=b"job spec")

    monkeypatch.setenv("COWORLD_EGRESS_RELAY_URL", "https://relay.test:3128")
    monkeypatch.setattr(runner_io, "_relay_http_client", lambda relay_url: _RelayClient(request))
    monkeypatch.setattr(runner_io.time, "sleep", sleeps.append)

    assert runner_io.read_data("https://example.test/job.json") == b"job spec"
    assert len(calls) == 2
    assert sleeps == [0.5]


def test_relay_routed_upload_data_retries_transient_transport_errors(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    calls = []
    sleeps: list[float] = []

    def request(method: str, uri: str, **kwargs):
        calls.append((method, uri, kwargs))
        if len(calls) == 1:
            raise httpx.ConnectError("relay connection failed")
        return _httpx_response(200, method=method)

    monkeypatch.setenv("COWORLD_EGRESS_RELAY_URL", "https://relay.test:3128")
    monkeypatch.setattr(runner_io, "_relay_http_client", lambda relay_url: _RelayClient(request))
    monkeypatch.setattr(runner_io.time, "sleep", sleeps.append)
    caplog.set_level(logging.WARNING, logger=runner_io.__name__)

    runner_io.upload_data("https://example.test/results.json", "{}", content_type="application/json")

    assert len(calls) == 2
    assert calls[0][0] == "PUT"
    assert calls[0][2]["content"] == b"{}"
    assert sleeps == [0.5]
    assert "Coworld relay request attempt 1/4 failed with ConnectError (HTTP status unavailable)" in caplog.messages


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


def test_relay_routed_upload_data_reraises_after_transport_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    sleeps: list[float] = []
    errors = [httpx.WriteError(f"write failed {attempt}") for attempt in range(4)]

    def request(method: str, uri: str, **kwargs):
        calls.append((method, uri, kwargs))
        raise errors[len(calls) - 1]

    monkeypatch.setenv("COWORLD_EGRESS_RELAY_URL", "https://relay.test:3128")
    monkeypatch.setattr(runner_io, "_relay_http_client", lambda relay_url: _RelayClient(request))
    monkeypatch.setattr(runner_io.time, "sleep", sleeps.append)

    with pytest.raises(httpx.WriteError) as exc_info:
        runner_io.upload_data("https://example.test/results.json", b"{}", content_type="application/json")

    assert exc_info.value is errors[-1]
    assert len(calls) == 4
    assert sleeps == [0.5, 1.0, 2.0]


def test_relay_routed_upload_file_rewinds_after_transport_error(monkeypatch: pytest.MonkeyPatch) -> None:
    uploaded_data = []
    sleeps: list[float] = []

    def request(method: str, uri: str, **kwargs):
        uploaded_data.append(kwargs["content"].read())
        if len(uploaded_data) == 1:
            raise httpx.WriteError("relay write failed")
        return _httpx_response(200, method=method)

    monkeypatch.setenv("COWORLD_EGRESS_RELAY_URL", "https://relay.test:3128")
    monkeypatch.setattr(runner_io, "_relay_http_client", lambda relay_url: _RelayClient(request))
    monkeypatch.setattr(runner_io.time, "sleep", sleeps.append)

    runner_io.upload_file(
        "https://example.test/replay.zstd",
        BytesIO(b"replay bytes"),
        size=12,
        content_type="application/zstd",
    )

    assert uploaded_data == [b"replay bytes", b"replay bytes"]
    assert sleeps == [0.5]


def test_direct_upload_file_streams_with_content_length_and_rewinds(monkeypatch: pytest.MonkeyPatch) -> None:
    uploaded_data = []
    content_lengths = []
    sleeps: list[float] = []

    def urlopen(request, *, timeout: int):
        uploaded_data.append(request.data.read())
        content_lengths.append(request.get_header("Content-length"))
        if len(uploaded_data) == 1:
            raise _http_error(request.full_url, 503)
        return _Response()

    monkeypatch.delenv("COWORLD_EGRESS_RELAY_URL", raising=False)
    monkeypatch.setattr(runner_io, "urlopen", urlopen)
    monkeypatch.setattr(runner_io.time, "sleep", sleeps.append)

    runner_io.upload_file(
        "https://example.test/player.zip",
        BytesIO(b"artifact bytes"),
        size=14,
        content_type="application/zip",
    )

    assert uploaded_data == [b"artifact bytes", b"artifact bytes"]
    assert content_lengths == ["14", "14"]
    assert sleeps == [0.5]


def test_upload_file_streams_to_file_uri(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    destination = tmp_path / "nested" / "player.zip"
    monkeypatch.delenv("COWORLD_EGRESS_RELAY_URL", raising=False)

    runner_io.upload_file(
        destination.as_uri(),
        BytesIO(b"artifact bytes"),
        size=14,
        content_type="application/zip",
    )

    assert destination.read_bytes() == b"artifact bytes"


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


def test_relay_routed_upload_data_does_not_retry_client_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    sleeps: list[float] = []

    def request(method: str, uri: str, **kwargs):
        calls.append((method, uri, kwargs))
        return _httpx_response(400, method=method)

    monkeypatch.setenv("COWORLD_EGRESS_RELAY_URL", "https://relay.test:3128")
    monkeypatch.setattr(runner_io, "_relay_http_client", lambda relay_url: _RelayClient(request))
    monkeypatch.setattr(runner_io.time, "sleep", sleeps.append)

    with pytest.raises(httpx.HTTPStatusError):
        runner_io.upload_data("https://example.test/results.json", b"{}", content_type="application/json")

    assert len(calls) == 1
    assert sleeps == []


def test_relay_http_client_follows_redirects(monkeypatch: pytest.MonkeyPatch) -> None:
    kwargs = {}
    sentinel = object()
    tls_context = object()

    def client(**values: object) -> object:
        kwargs.update(values)
        return sentinel

    monkeypatch.setenv("COWORLD_EGRESS_RELAY_CLIENT_CERT_FILE", "/tls/client.crt")
    monkeypatch.setenv("COWORLD_EGRESS_RELAY_CLIENT_KEY_FILE", "/tls/client.key")
    monkeypatch.setenv("COWORLD_EGRESS_RELAY_CA_FILE", "/tls/ca.crt")
    monkeypatch.setattr(relay_client, "egress_relay_ssl_context", lambda **_kwargs: tls_context)
    monkeypatch.setattr(
        runner_io.httpx,
        "Proxy",
        lambda url, *, ssl_context: (url, ssl_context),
    )
    monkeypatch.setattr(runner_io.httpx, "Client", client)

    assert runner_io._relay_http_client("https://relay.test:3128") is sentinel
    assert kwargs == {
        "proxy": ("https://relay.test:3128", tls_context),
        "timeout": 60.0,
        "follow_redirects": True,
    }


@pytest.mark.parametrize("streaming", [False, True])
def test_upload_reads_current_mounted_target(tmp_path: Path, streaming: bool) -> None:
    manifest = tmp_path / "targets.json"
    uri = f"coworld-artifact+{manifest.as_uri()}#results.json"
    for generation in range(2):
        output = tmp_path / f"result-{generation}.json"
        manifest.write_text(
            ArtifactUploadTargets(
                expires_at=datetime.now(UTC) + timedelta(hours=6), targets={"results.json": output.as_uri()}
            ).model_dump_json()
        )
        if streaming:
            runner_io.upload_file(uri, BytesIO(b"{}"), size=2, content_type="application/json")
        else:
            runner_io.upload_data(uri, b"{}", content_type="application/json")
        assert output.read_bytes() == b"{}"


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("failure", ["expired", "missing-key"])
def test_upload_rejects_unusable_mounted_target(tmp_path: Path, streaming: bool, failure: str) -> None:
    manifest = tmp_path / "targets.json"
    output = tmp_path / "result.json"
    manifest.write_text(
        ArtifactUploadTargets(
            expires_at=datetime.now(UTC) + timedelta(hours=-1 if failure == "expired" else 6),
            targets={"results.json": output.as_uri()} if failure == "expired" else {},
        ).model_dump_json()
    )
    uri = f"coworld-artifact+{manifest.as_uri()}#results.json"
    with pytest.raises(ValueError if failure == "expired" else KeyError):
        if streaming:
            runner_io.upload_file(uri, BytesIO(b"{}"), size=2, content_type="application/json")
        else:
            runner_io.upload_data(uri, b"{}", content_type="application/json")
    assert not output.exists()
