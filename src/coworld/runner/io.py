from __future__ import annotations

import time
from pathlib import Path
from typing import Literal
from urllib.error import HTTPError
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field

_WRITE_RETRY_DELAYS_SECONDS = (0.5, 1.0, 2.0)
_RETRYABLE_WRITE_STATUS_CODES = {429, 500, 502, 503, 504}

RunnerErrorType = Literal[
    "player_error",
    "no_players_connected",
    "game_unhealthy",
    "game_contract_violation",
    "results_missing",
    "results_malformed",
    "replay_missing",
    "replay_unloadable",
    "episode_timeout",
    "crash",
]


class RunnerError(BaseModel):
    error_type: RunnerErrorType
    message: str
    failed_policy_index: int | None = None


class GameEpisodeError(BaseModel):
    """Terminal episode failure declared by the game runnable."""

    model_config = ConfigDict(extra="forbid")

    error_type: Literal["player_error"]
    message: str = Field(min_length=1, max_length=2000)
    failed_policy_index: int = Field(ge=0)


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


def read_data(uri: str) -> bytes:
    parsed = urlparse(uri)
    if parsed.scheme in ("http", "https"):
        with urlopen(uri, timeout=30) as response:
            return response.read()
    if parsed.scheme == "file":
        return Path(unquote(parsed.path)).read_bytes()
    if parsed.scheme == "":
        return Path(uri).read_bytes()
    raise ValueError(f"Unsupported URI for read_data: {uri}")


def write_data(
    uri: str,
    data: bytes | str,
    *,
    content_type: str,
    http_method: Literal["POST", "PUT"] = "PUT",
) -> None:
    _write_data(uri, data, content_type=content_type, http_method=http_method)


def post_data(uri: str, data: bytes | str, *, content_type: str) -> None:
    write_data(uri, data, content_type=content_type, http_method="POST")


def upload_data(uri: str, data: bytes | str, *, content_type: str) -> None:
    write_data(uri, data, content_type=content_type, http_method="PUT")


def _write_data(uri: str, data: bytes | str, *, content_type: str, http_method: Literal["POST", "PUT"]) -> None:
    if isinstance(data, str):
        data = data.encode()

    parsed = urlparse(uri)
    if parsed.scheme in ("http", "https"):
        request = Request(uri, data=data, method=http_method)
        request.add_header("Content-Type", content_type)
        for retry_index in range(len(_WRITE_RETRY_DELAYS_SECONDS) + 1):
            try:
                with urlopen(request, timeout=60):
                    return
            except HTTPError as exc:
                if exc.code not in _RETRYABLE_WRITE_STATUS_CODES or retry_index == len(_WRITE_RETRY_DELAYS_SECONDS):
                    raise
                time.sleep(_WRITE_RETRY_DELAYS_SECONDS[retry_index])
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
    raise ValueError(f"Unsupported URI for write_data: {uri}")
