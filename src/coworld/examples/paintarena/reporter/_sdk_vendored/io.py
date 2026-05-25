"""URI I/O helpers and env-var URI accessors for reporter implementations.

Implements the I/O surface every reporter in this repo needs:

- Environment-variable URI accessors (``COGAME_EPISODE_BUNDLE_URI``,
  ``COGAME_REPORT_URI``).
- ``read_uri`` / ``write_uri`` dispatched over ``file://`` and
  ``http(s)://`` (presigned S3 surfaces as ordinary HTTPS), with retry on
  429/5xx using exponential backoff.

Behavior is the canonical-contract surface the two concrete reporters
shipped — see metta's ``packages/coworld/src/coworld/runner/io.py`` for the
upstream reference. ``read_uri`` and ``write_uri`` are sufficient for the
reporter side of that contract; the SDK does not import boto3 or the AWS
SDK because every S3 URI a reporter sees is presigned and resolves over
HTTPS already.

Both ``requests`` and ``time`` are imported as ordinary modules; tests
that need to stub HTTP behavior can ``monkeypatch.setattr(requests,
"request", ...)`` and ``monkeypatch.setattr(time, "sleep", ...)``.
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
from pathlib import Path
from typing import Any

import requests
from pydantic import BaseModel

# Status codes treated as transient. Any other 4xx is a permanent client
# error and is not retried.
_HTTP_RETRY_STATUSES = {429, 500, 502, 503, 504}

# Total attempts (initial + retries). 5 attempts with the backoff schedule
# below adds up to ~7.5s of waiting in the worst case before giving up.
_HTTP_MAX_ATTEMPTS = 5


class ReporterInputs(BaseModel):
    """The two URIs every reporter is invoked with.

    Reads from ``COGAME_EPISODE_BUNDLE_URI`` (input: episode bundle zip)
    and ``COGAME_REPORT_URI`` (output: where the reporter writes its
    output zip). Both are required.
    """

    episode_bundle_uri: str
    report_uri: str


def load_reporter_inputs() -> ReporterInputs:
    """Read the two canonical env vars. Raises ``KeyError`` if missing."""
    return ReporterInputs(
        episode_bundle_uri=os.environ["COGAME_EPISODE_BUNDLE_URI"],
        report_uri=os.environ["COGAME_REPORT_URI"],
    )


def _file_path_from_uri(uri: str) -> Path:
    parsed = urllib.parse.urlparse(uri)
    return Path(urllib.parse.unquote(parsed.path))


def read_uri(uri: str) -> bytes:
    """Read the bytes pointed at by ``uri``. Supports ``file://`` and
    ``http(s)://`` (presigned S3 surfaces as HTTPS).
    """
    scheme = urllib.parse.urlparse(uri).scheme.lower()
    if scheme == "file":
        return _file_path_from_uri(uri).read_bytes()
    if scheme in ("http", "https"):
        return _http_request_with_retry("GET", uri).content
    raise ValueError(f"unsupported URI scheme {scheme!r} for read: {uri}")


def write_uri(uri: str, payload: bytes, content_type: str) -> None:
    """Write ``payload`` to ``uri``. Supports ``file://`` (creates parent
    dirs) and ``http(s)://`` PUT (Content-Type honored).
    """
    scheme = urllib.parse.urlparse(uri).scheme.lower()
    if scheme == "file":
        path = _file_path_from_uri(uri)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return
    if scheme in ("http", "https"):
        _http_request_with_retry("PUT", uri, data=payload, headers={"Content-Type": content_type})
        return
    raise ValueError(f"unsupported URI scheme {scheme!r} for write: {uri}")


def _http_request_with_retry(
    method: str,
    uri: str,
    *,
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> requests.Response:
    """Single-host HTTP request with retry on transient (429/5xx) status.

    Exponential backoff capped at 8s. Five total attempts. Any non-retryable
    response (e.g. 404) raises immediately via ``raise_for_status``.
    """
    delay = 0.5
    for attempt in range(1, _HTTP_MAX_ATTEMPTS + 1):
        resp = requests.request(method, uri, data=data, headers=headers, timeout=30)
        if resp.status_code < 400:
            return resp
        if resp.status_code not in _HTTP_RETRY_STATUSES or attempt == _HTTP_MAX_ATTEMPTS:
            resp.raise_for_status()
        time.sleep(delay)
        delay = min(delay * 2, 8.0)
    raise RuntimeError("unreachable")  # loop above either returns or raises


def read_json(uri: str) -> Any:
    """Read ``uri`` and decode the bytes as UTF-8 JSON."""
    return json.loads(read_uri(uri).decode("utf-8"))
