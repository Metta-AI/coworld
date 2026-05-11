from __future__ import annotations

from pathlib import Path
from typing import Literal
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

from pydantic import BaseModel


class RunnerError(BaseModel):
    error_type: Literal["crash"]
    message: str


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


def post_data(uri: str, data: bytes | str, *, content_type: str) -> None:
    _write_data(uri, data, content_type=content_type, http_method="POST")


def upload_data(uri: str, data: bytes | str, *, content_type: str) -> None:
    _write_data(uri, data, content_type=content_type, http_method="PUT")


def _write_data(uri: str, data: bytes | str, *, content_type: str, http_method: Literal["POST", "PUT"]) -> None:
    if isinstance(data, str):
        data = data.encode()

    parsed = urlparse(uri)
    if parsed.scheme in ("http", "https"):
        request = Request(uri, data=data, method=http_method)
        request.add_header("Content-Type", content_type)
        with urlopen(request, timeout=60):
            return
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
