from __future__ import annotations

import logging
import os
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Iterator, Literal, Protocol
from urllib.error import HTTPError
from urllib.parse import unquote, urlparse, urlsplit, urlunsplit
from urllib.request import Request, urlopen

import httpx
from pydantic import BaseModel, ConfigDict, Field
from tenacity import RetryCallState, Retrying, retry_if_exception, stop_after_attempt, wait_chain, wait_fixed

_RETRY_DELAYS_SECONDS = (0.5, 1.0, 2.0)
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

logger = logging.getLogger(__name__)

RunnerErrorType = Literal[
    "player_error",
    "player_never_started",
    "game_unhealthy",
    "game_contract_violation",
    "results_missing",
    "results_malformed",
    "replay_missing",
    "replay_unloadable",
    "episode_timeout",
    "crash",
    "worker_error",
    "config_error",
    "player_file_unavailable",
    "player_file_mismatch",
]


class RunnerError(BaseModel):
    error_type: RunnerErrorType
    message: str
    failed_policy_index: int | None = None


class GamePlayerFailure(BaseModel):
    """Terminal player failure declared by the game runnable."""

    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=2000)
    failed_policy_index: int = Field(ge=0)


class PlayerRuntimeStatus(BaseModel):
    """Runner-observed process state for one hosted player slot."""

    model_config = ConfigDict(extra="forbid")

    slot: int = Field(ge=0)
    state: Literal["running", "exited", "not_started", "unavailable"]
    exit_code: int | None = None
    reason: str | None = None
    finished_at: datetime | None = None


class PlayerRuntimeStatuses(BaseModel):
    """Runner-owned player process snapshot captured before pod teardown."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1"] = "1"
    players: list[PlayerRuntimeStatus]


class RewindableBinaryStream(Protocol):
    def seek(self, offset: int, whence: int = 0, /) -> int: ...

    def read(self, size: int = -1, /) -> bytes: ...

    def __iter__(self) -> Iterator[bytes]: ...


class _ExactSizeStream:
    def __init__(self, file: RewindableBinaryStream, size: int) -> None:
        self.file = file
        self.size = size
        self.remaining = size

    def seek(self, offset: int, whence: int = 0, /) -> int:
        position = self.file.seek(offset, whence)
        self.remaining = self.size - position
        return position

    def read(self, size: int = -1, /) -> bytes:
        if self.remaining == 0:
            if self.file.read(1):
                raise ValueError("upload source grew beyond its declared Content-Length")
            return b""
        chunk = self.file.read(self.remaining if size < 0 else min(size, self.remaining))
        if not chunk:
            raise ValueError("upload source ended before its declared Content-Length")
        self.remaining -= len(chunk)
        return chunk

    def __iter__(self) -> Iterator[bytes]:
        while chunk := self.read(65536):
            yield chunk


class RunnerEpisodeError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        error_type: RunnerErrorType,
        failed_policy_index: int | None = None,
    ):
        super().__init__(message)
        self.error_type = error_type
        self.failed_policy_index = failed_policy_index


def redact_uri(uri: str) -> str:
    parts = urlsplit(uri)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", parts.fragment))


def exception_summary(error: BaseException) -> str:
    if isinstance(error, httpx.HTTPStatusError):
        status = error.response.status_code
    elif isinstance(error, HTTPError):
        status = error.code
    else:
        status = "unavailable"
    return f"{type(error).__name__} (HTTP status {status})"


def _is_retryable_relay_error(error: BaseException) -> bool:
    return isinstance(error, httpx.TransportError) or (
        isinstance(error, httpx.HTTPStatusError) and error.response.status_code in _RETRYABLE_STATUS_CODES
    )


def _log_relay_retry(retry_state: RetryCallState) -> None:
    assert retry_state.outcome is not None
    error = retry_state.outcome.exception()
    assert error is not None
    request = getattr(error, "_request", None)
    if isinstance(request, httpx.Request):
        logger.warning(
            "Coworld relay request attempt %d/%d failed with %s for %s",
            retry_state.attempt_number,
            len(_RETRY_DELAYS_SECONDS) + 1,
            exception_summary(error),
            redact_uri(str(request.url)),
        )
    else:
        logger.warning(
            "Coworld relay request attempt %d/%d failed with %s",
            retry_state.attempt_number,
            len(_RETRY_DELAYS_SECONDS) + 1,
            exception_summary(error),
        )


def _relay_request_attempts(attempts: int = len(_RETRY_DELAYS_SECONDS) + 1) -> Retrying:
    return Retrying(
        retry=retry_if_exception(_is_retryable_relay_error),
        stop=stop_after_attempt(attempts),
        wait=(
            wait_chain(*(wait_fixed(delay) for delay in _RETRY_DELAYS_SECONDS[: attempts - 1]))
            if attempts > 1
            else wait_fixed(0)
        ),
        before_sleep=_log_relay_retry,
        sleep=time.sleep,
        reraise=True,
    )


def read_data(uri: str) -> bytes:
    parsed = urlparse(uri)
    if parsed.scheme in ("http", "https"):
        relay_url = os.environ.get("COWORLD_EGRESS_RELAY_URL")
        if relay_url is not None:
            if parsed.scheme != "https":
                raise ValueError("relay-routed reads require an https URI")
            for attempt in _relay_request_attempts():
                with attempt:
                    with _relay_http_client(relay_url) as client:
                        response = client.get(uri)
                        response.raise_for_status()
                        return response.content
            raise AssertionError("unreachable")
        with urlopen(uri, timeout=30) as response:
            return response.read()
    if parsed.scheme == "file":
        return Path(unquote(parsed.path)).read_bytes()
    if parsed.scheme == "":
        return Path(uri).read_bytes()
    raise ValueError(f"Unsupported URI for read_data: {redact_uri(uri)}")


def write_data(uri: str, data: bytes | str, *, content_type: str) -> None:
    if isinstance(data, str):
        data = data.encode()

    parsed = urlparse(uri)
    if parsed.scheme in ("http", "https"):
        relay_url = os.environ.get("COWORLD_EGRESS_RELAY_URL")
        if relay_url is not None:
            for attempt in _relay_request_attempts():
                with attempt:
                    with _relay_http_client(relay_url) as client:
                        response = client.put(
                            uri,
                            content=data,
                            headers={"Content-Type": content_type},
                        )
                        if response.status_code >= 400:
                            response.raise_for_status()
                        return
            raise AssertionError("unreachable")
        request = Request(uri, data=data, method="PUT")
        request.add_header("Content-Type", content_type)
        for retry_index in range(len(_RETRY_DELAYS_SECONDS) + 1):
            try:
                with urlopen(request, timeout=60):
                    return
            except HTTPError as exc:
                if exc.code not in _RETRYABLE_STATUS_CODES or retry_index == len(_RETRY_DELAYS_SECONDS):
                    raise
                time.sleep(_RETRY_DELAYS_SECONDS[retry_index])
    if parsed.scheme == "file":
        path = Path(unquote(parsed.path))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return
    if parsed.scheme == "":
        path = Path(uri)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return
    raise ValueError(f"Unsupported URI for write_data: {redact_uri(uri)}")


def upload_data(uri: str, data: bytes | str, *, content_type: str) -> None:
    write_data(uri, data, content_type=content_type)


def upload_file(
    uri: str,
    file: RewindableBinaryStream,
    *,
    size: int,
    content_type: str,
    attempts: int = len(_RETRY_DELAYS_SECONDS) + 1,
) -> None:
    parsed = urlparse(uri)
    stream = _ExactSizeStream(file, size)
    if parsed.scheme in ("http", "https"):
        relay_url = os.environ.get("COWORLD_EGRESS_RELAY_URL")
        if relay_url is not None:
            for attempt in _relay_request_attempts(attempts):
                with attempt:
                    stream.seek(0)
                    with _relay_http_client(relay_url) as client:
                        response = client.put(
                            uri,
                            content=stream,
                            headers={"Content-Type": content_type, "Content-Length": str(size)},
                        )
                        if response.status_code >= 400:
                            response.raise_for_status()
                        return
            raise AssertionError("unreachable")
        for retry_index in range(attempts):
            stream.seek(0)
            request = Request(uri, data=stream, method="PUT")
            request.add_header("Content-Type", content_type)
            request.add_header("Content-Length", str(size))
            try:
                with urlopen(request, timeout=60):
                    return
            except HTTPError as exc:
                if exc.code not in _RETRYABLE_STATUS_CODES or retry_index == attempts - 1:
                    raise
                time.sleep(_RETRY_DELAYS_SECONDS[retry_index])
    if parsed.scheme in ("", "file"):
        path = Path(unquote(parsed.path)) if parsed.scheme == "file" else Path(uri)
        path.parent.mkdir(parents=True, exist_ok=True)
        stream.seek(0)
        with path.open("wb") as destination:
            shutil.copyfileobj(stream, destination, length=65536)
        return
    raise ValueError(f"Unsupported URI for upload_file: {redact_uri(uri)}")


def _relay_http_client(relay_url: str) -> httpx.Client:
    return httpx.Client(proxy=relay_url, timeout=60.0, follow_redirects=True)
