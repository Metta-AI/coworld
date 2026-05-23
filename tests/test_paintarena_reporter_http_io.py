"""Tests for the HTTP path of read_uri / write_uri and _http_request_with_retry.

The reporter's HTTP I/O is one of the SDK-extraction candidates listed in
``Metta-AI/reporters/docs/REPORTER_DESIGN.md``
(https://github.com/Metta-AI/reporters/blob/main/docs/REPORTER_DESIGN.md).
These tests pin the retry policy contract (retry on 429/5xx with
exponential backoff, no retry on other 4xx, capped attempts) so the
extraction can move the code without changing the behavior.

Note: the current Coworld reporter contract in ``docs/roles/reporter.md``
(this package) supersedes the v1 contract these tests target; reconciliation
is tracked separately.
"""

from __future__ import annotations

from typing import Any

import pytest
import requests

from coworld.examples.paintarena.reporter import paint_arena_summarizer as par


class FakeResponse:
    """Minimal stand-in for requests.Response covering the surface the reporter uses."""

    def __init__(self, status_code: int, content: bytes = b"") -> None:
        self.status_code = status_code
        self.content = content

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)  # type: ignore[arg-type]


def _install_request_stub(monkeypatch: pytest.MonkeyPatch, responses: list[FakeResponse]) -> list[dict[str, Any]]:
    """Replace requests.request with a stub that yields the queued responses.

    Returns a list that the stub appends each call's kwargs to, for assertion.
    """
    calls: list[dict[str, Any]] = []
    iterator = iter(responses)

    def fake_request(method: str, url: str, **kwargs: Any) -> FakeResponse:
        calls.append({"method": method, "url": url, **kwargs})
        try:
            return next(iterator)
        except StopIteration:  # pragma: no cover -- a test that hits this is buggy
            raise AssertionError("request stub exhausted; expected fewer calls") from None

    monkeypatch.setattr(par.requests, "request", fake_request)
    monkeypatch.setattr(par.time, "sleep", lambda _seconds: None)  # don't slow tests
    return calls


def test_read_uri_http_success_no_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_request_stub(monkeypatch, [FakeResponse(200, b"hello")])
    assert par.read_uri("https://example.test/path") == b"hello"
    assert len(calls) == 1
    assert calls[0]["method"] == "GET"


@pytest.mark.parametrize("transient_status", [429, 500, 502, 503, 504])
def test_read_uri_retries_on_transient_status(monkeypatch: pytest.MonkeyPatch, transient_status: int) -> None:
    calls = _install_request_stub(
        monkeypatch,
        [FakeResponse(transient_status), FakeResponse(transient_status), FakeResponse(200, b"ok")],
    )
    assert par.read_uri("https://example.test/path") == b"ok"
    assert len(calls) == 3


def test_read_uri_no_retry_on_client_error(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_request_stub(monkeypatch, [FakeResponse(404)])
    with pytest.raises(requests.HTTPError):
        par.read_uri("https://example.test/path")
    assert len(calls) == 1  # no retry on non-retryable 4xx


def test_read_uri_retries_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    """5 attempts max; if every response is transient the final one raises."""
    calls = _install_request_stub(monkeypatch, [FakeResponse(503) for _ in range(par._HTTP_MAX_ATTEMPTS)])
    with pytest.raises(requests.HTTPError):
        par.read_uri("https://example.test/path")
    assert len(calls) == par._HTTP_MAX_ATTEMPTS


def test_write_uri_http_put_sends_payload_and_content_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_request_stub(monkeypatch, [FakeResponse(200)])
    par.write_uri("https://example.test/upload", b'{"ok": true}', content_type="application/json")
    assert len(calls) == 1
    assert calls[0]["method"] == "PUT"
    assert calls[0]["url"] == "https://example.test/upload"
    assert calls[0]["data"] == b'{"ok": true}'
    assert calls[0]["headers"] == {"Content-Type": "application/json"}


def test_write_uri_http_put_retries_on_503(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_request_stub(monkeypatch, [FakeResponse(503), FakeResponse(200)])
    par.write_uri("http://example.test/upload", b"payload", content_type="text/plain")
    assert [c["method"] for c in calls] == ["PUT", "PUT"]


def test_backoff_grows_exponentially_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sleep delays follow 0.5, 1.0, 2.0, 4.0 between the 5 attempts (capped at 8)."""
    sleeps: list[float] = []
    monkeypatch.setattr(par.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(
        par.requests,
        "request",
        lambda *a, **kw: FakeResponse(503),
    )
    with pytest.raises(requests.HTTPError):
        par.read_uri("https://example.test/path")
    # 5 attempts -> 4 sleeps between them.
    assert sleeps == [0.5, 1.0, 2.0, 4.0]


def test_unsupported_scheme_read_raises() -> None:
    with pytest.raises(ValueError, match="unsupported URI scheme"):
        par.read_uri("ftp://example.test/x")


def test_unsupported_scheme_write_raises() -> None:
    with pytest.raises(ValueError, match="unsupported URI scheme"):
        par.write_uri("ftp://example.test/x", b"x", content_type="text/plain")
