from __future__ import annotations

import os
import zipfile
from io import BytesIO
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

from pydantic import BaseModel

HTTP_USER_AGENT = "coworld-grader-template/0.1"


class BundleManifest(BaseModel):
    status: str


class Grade(BaseModel):
    grader_id: str
    score: float


def read_data(uri: str) -> bytes:
    parsed = urlparse(uri)
    if parsed.scheme in ("http", "https"):
        request = Request(uri, headers={"User-Agent": HTTP_USER_AGENT})
        with urlopen(request, timeout=30) as response:
            return response.read()
    if parsed.scheme == "file":
        return Path(unquote(parsed.path)).read_bytes()
    if parsed.scheme == "":
        return Path(uri).read_bytes()
    raise ValueError(f"Unsupported URI for read_data: {uri}")


def write_data(uri: str, data: bytes) -> None:
    parsed = urlparse(uri)
    if parsed.scheme in ("http", "https"):
        request = Request(uri, data=data, method="PUT")
        request.add_header("Content-Type", "application/json")
        request.add_header("User-Agent", HTTP_USER_AGENT)
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


def grade_bundle(bundle_uri: str) -> Grade:
    with zipfile.ZipFile(BytesIO(read_data(bundle_uri))) as bundle:
        manifest = BundleManifest.model_validate_json(bundle.read("manifest.json"))
    return Grade(grader_id="template-grader", score=1.0 if manifest.status == "success" else 0.0)


def main() -> None:
    grade = grade_bundle(os.environ["COGAME_EPISODE_BUNDLE_URI"])
    write_data(os.environ["COGAME_GRADE_URI"], f"{grade.model_dump_json(indent=2)}\n".encode("utf-8"))


if __name__ == "__main__":
    main()
