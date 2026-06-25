from __future__ import annotations

import os
import zipfile
from collections.abc import Sequence
from io import BytesIO
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

from pydantic import BaseModel

HTTP_USER_AGENT = "coworld-diagnoser-template/0.1"
ZIP_ENTRY_MTIME = (1980, 1, 1, 0, 0, 0)


class DiagnosisManifest(BaseModel):
    diagnoser_id: str
    render: str


class DiagnosisFindings(BaseModel):
    diagnoser_id: str
    target_policy_uri: str
    summary: str


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


def build_diagnosis(bundle_uri: str, target_policy_uri: str) -> bytes:
    read_data(bundle_uri)
    findings = DiagnosisFindings(
        diagnoser_id="template-diagnoser",
        target_policy_uri=target_policy_uri,
        summary="Inspect this policy against the bundled episode replay and results.",
    )
    manifest = DiagnosisManifest(diagnoser_id=findings.diagnoser_id, render="diagnosis.md")
    markdown = (
        "# Coworld Diagnosis\n\n"
        f"- target_policy_uri: `{findings.target_policy_uri}`\n"
        f"- summary: {findings.summary}\n"
    )
    return deterministic_zip(
        [
            ("manifest.json", f"{manifest.model_dump_json(indent=2)}\n".encode("utf-8")),
            ("diagnosis.md", markdown.encode("utf-8")),
            ("findings.json", f"{findings.model_dump_json(indent=2)}\n".encode("utf-8")),
        ]
    )


def main() -> None:
    write_data(
        os.environ["COGAME_DIAGNOSIS_URI"],
        build_diagnosis(os.environ["COGAME_EPISODE_BUNDLE_URI"], os.environ["COGAME_TARGET_POLICY_URI"]),
    )


if __name__ == "__main__":
    main()
