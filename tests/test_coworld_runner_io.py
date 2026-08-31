import logging
from email.message import Message
from io import BytesIO
from urllib.error import HTTPError

import httpx
import pytest

from coworld.runner import io as runner_io


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
    monkeypatch.setenv("COWORLD_EGRESS_RELAY_URL", "http://relay.test:3128")

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

    monkeypatch.setenv("COWORLD_EGRESS_RELAY_URL", "http://relay.test:3128")
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

    monkeypatch.setenv("COWORLD_EGRESS_RELAY_URL", "http://relay.test:3128")
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

    monkeypatch.setenv("COWORLD_EGRESS_RELAY_URL", "http://relay.test:3128")
    monkeypatch.setattr(runner_io, "_relay_http_client", lambda relay_url: _RelayClient(request))
    monkeypatch.setattr(runner_io.time, "sleep", sleeps.append)
    caplog.set_level(logging.WARNING, logger=runner_io.__name__)

    runner_io.upload_data("https://example.test/results.json", "{}", content_type="application/json")

    assert len(calls) == 2
    assert calls[0][0] == "PUT"
    assert calls[0][2]["content"] == b"{}"
    assert sleeps == [0.5]
    assert "Coworld relay request attempt 1/4 failed with ConnectError: relay connection failed" in caplog.messages


def test_relay_routed_upload_data_reraises_after_transport_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    sleeps: list[float] = []
    errors = [httpx.WriteError(f"write failed {attempt}") for attempt in range(4)]

    def request(method: str, uri: str, **kwargs):
        calls.append((method, uri, kwargs))
        raise errors[len(calls) - 1]

    monkeypatch.setenv("COWORLD_EGRESS_RELAY_URL", "http://relay.test:3128")
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

    monkeypatch.setenv("COWORLD_EGRESS_RELAY_URL", "http://relay.test:3128")
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


def test_relay_routed_upload_data_does_not_retry_client_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    sleeps: list[float] = []

    def request(method: str, uri: str, **kwargs):
        calls.append((method, uri, kwargs))
        return _httpx_response(400, method=method)

    monkeypatch.setenv("COWORLD_EGRESS_RELAY_URL", "http://relay.test:3128")
    monkeypatch.setattr(runner_io, "_relay_http_client", lambda relay_url: _RelayClient(request))
    monkeypatch.setattr(runner_io.time, "sleep", sleeps.append)

    with pytest.raises(httpx.HTTPStatusError):
        runner_io.upload_data("https://example.test/results.json", b"{}", content_type="application/json")

    assert len(calls) == 1
    assert sleeps == []


def test_relay_http_client_follows_redirects(monkeypatch: pytest.MonkeyPatch) -> None:
    kwargs = {}
    sentinel = object()

    def client(**values: object) -> object:
        kwargs.update(values)
        return sentinel

    monkeypatch.setattr(runner_io.httpx, "Client", client)

    assert runner_io._relay_http_client("http://relay.test:3128") is sentinel
    assert kwargs == {"proxy": "http://relay.test:3128", "timeout": 60.0, "follow_redirects": True}
