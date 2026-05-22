from urllib.error import HTTPError

import pytest

from coworld.runner import io as runner_io


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        return None


def _http_error(url: str, code: int) -> HTTPError:
    return HTTPError(url, code, "error", hdrs=None, fp=None)


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


def test_write_data_can_post_to_signed_uri(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def urlopen(request, *, timeout: int):
        calls.append((request, timeout))
        return _Response()

    monkeypatch.setattr(runner_io, "urlopen", urlopen)

    runner_io.write_data(
        "https://example.test/upload",
        "{}",
        content_type="application/json",
        http_method="POST",
    )

    assert len(calls) == 1
    assert calls[0][0].get_method() == "POST"
