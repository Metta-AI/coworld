from __future__ import annotations

import json
import os
import zipfile
from collections.abc import Sequence
from io import BytesIO
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

from pydantic import BaseModel

HTTP_USER_AGENT = "coworld-reporter-template/0.1"
ZIP_ENTRY_MTIME = (1980, 1, 1, 0, 0, 0)


class ArtifactRef(BaseModel):
    uri: str
    media_type: str
    encoding: str = "identity"


class EpisodeArtifacts(BaseModel):
    results: ArtifactRef | None = None
    replay: ArtifactRef | None = None


class EpisodeInput(BaseModel):
    episode_request_id: str
    status: str
    artifacts: EpisodeArtifacts


class ReportRequest(BaseModel):
    request_id: str
    episodes: list[EpisodeInput]
    report_uri: str


class ReportManifest(BaseModel):
    reporter_id: str
    render: str


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
        request.add_header("Content-Type", "application/zip")
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


def deterministic_zip(entries: Sequence[tuple[str, bytes]]) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, payload in entries:
            info = zipfile.ZipInfo(filename=name, date_time=ZIP_ENTRY_MTIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, payload)
    return buffer.getvalue()


def summarize(request: ReportRequest) -> str:
    lines = [f"# Coworld Report {request.request_id}", ""]
    for episode in request.episodes:
        lines.append(f"- {episode.episode_request_id}: {episode.status}")
    return "\n".join(lines) + "\n"


def build_report_zip(request: ReportRequest) -> bytes:
    manifest = ReportManifest(reporter_id="template-reporter", render="summary.md")
    return deterministic_zip(
        [
            ("manifest.json", f"{manifest.model_dump_json(indent=2)}\n".encode("utf-8")),
            ("summary.md", summarize(request).encode("utf-8")),
            ("request.json", f"{json.dumps(request.model_dump(mode='json'), indent=2)}\n".encode("utf-8")),
        ]
    )


def main() -> None:
    request = ReportRequest.model_validate_json(os.environ["COGAME_REPORT_REQUEST"])
    write_data(request.report_uri, build_report_zip(request))


if __name__ == "__main__":
    main()
