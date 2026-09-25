from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal

import httpx
from pydantic import BaseModel

from coworld.api_client import CoworldApiClient, EpisodeArtifactCategory, EpisodeDownloadEntry


class DownloadResult(BaseModel):
    kind: Literal["artifact"] = "artifact"
    episode_request_id: str
    artifact_id: str
    version: str | None
    filename: str
    encoding: str
    state: Literal["completed", "pending", "not_produced", "unavailable", "failed", "refresh_required"]
    path: str | None = None
    size: int | None = None
    sha256: str | None = None
    http_status: int | None = None


class UnavailableDownloadSelection(BaseModel):
    kind: Literal["selector"] = "selector"
    id: str
    state: Literal["unavailable"] = "unavailable"


def write_json_atomic(path: Path, value: BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(value.model_dump_json())
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def download_episode_file(entry: EpisodeDownloadEntry, directory: Path, storage: httpx.Client) -> DownloadResult:
    result = DownloadResult(
        episode_request_id=entry.episode_request_id,
        artifact_id=entry.artifact_id,
        version=entry.version,
        filename=entry.filename,
        encoding=entry.encoding,
        state="failed" if entry.state == "ready" else entry.state,
    )
    if entry.state != "ready":
        return result
    assert entry.version is not None
    identity = hashlib.sha256(f"{entry.artifact_id}:{entry.version}".encode()).hexdigest()
    folder = directory / identity
    if Path(entry.filename).name != entry.filename or entry.filename in ("", ".", ".."):
        raise ValueError("Manifest filename must be a single filename")
    destination = folder / entry.filename
    receipt = folder / "download.json"
    if receipt.exists() and destination.is_file():
        previous = DownloadResult.model_validate_json(receipt.read_text())
        with destination.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if (
            previous.artifact_id == entry.artifact_id
            and previous.version == entry.version
            and previous.sha256 == digest
            and previous.size == destination.stat().st_size
        ):
            return previous
    folder.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=folder, delete=False) as stream:
        temporary = Path(stream.name)
        digest = hashlib.sha256()
        size = 0
        try:
            if entry.inline_json is not None:
                content = json.dumps(entry.inline_json, sort_keys=True).encode()
                stream.write(content)
                digest.update(content)
                size = len(content)
            else:
                assert entry.url is not None and entry.etag is not None and entry.size is not None
                with storage.stream("GET", entry.url, headers={"If-Match": entry.etag}) as response:
                    if response.status_code in (403, 404, 412):
                        return result.model_copy(
                            update={"state": "refresh_required", "http_status": response.status_code}
                        )
                    if response.status_code != 200:
                        return result.model_copy(update={"http_status": response.status_code})
                    for chunk in response.iter_raw():
                        stream.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
                if size != entry.size:
                    return result
            stream.flush()
            os.fsync(stream.fileno())
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
    result.state = "completed"
    result.path = str(destination.relative_to(directory))
    result.size = size
    result.sha256 = digest.hexdigest()
    write_json_atomic(receipt, result)
    return result


def download_episodes(
    client: CoworldApiClient,
    ids: list[str],
    *,
    include: list[EpisodeArtifactCategory],
    directory: Path,
    agents: list[int] | None = None,
    concurrency: int = 4,
    on_result: Callable[[DownloadResult], None] | None = None,
) -> bool:
    """Stream an append-only receipt log; completed versioned files survive interrupted runs."""
    directory.mkdir(parents=True, exist_ok=True)
    incomplete = False
    with (
        httpx.Client(timeout=60, follow_redirects=True) as storage,
        ThreadPoolExecutor(max_workers=concurrency) as executor,
        (directory / "manifest.jsonl").open("a") as log,
    ):
        cursor = None
        while True:
            page = client.episode_download_manifest(ids, include=include, agents=agents, cursor=cursor)
            incomplete |= bool(page.unavailable_ids)
            for unavailable in page.unavailable_ids:
                log.write(UnavailableDownloadSelection(id=unavailable).model_dump_json() + "\n")
            results = list(executor.map(lambda entry: download_episode_file(entry, directory, storage), page.entries))
            refresh_ids = sorted({r.episode_request_id for r in results if r.state == "refresh_required"})
            if refresh_ids:
                # Refresh this bounded page's affected episodes once, never the full selection.
                refresh_cursor = None
                replacements: dict[str, DownloadResult] = {}
                wanted = {r.artifact_id for r in results if r.state == "refresh_required"}
                while True:
                    refreshed = client.episode_download_manifest(
                        refresh_ids,
                        include=include,
                        agents=agents,
                        cursor=refresh_cursor,
                    )
                    for replacement in executor.map(
                        lambda entry: download_episode_file(entry, directory, storage),
                        [entry for entry in refreshed.entries if entry.artifact_id in wanted],
                    ):
                        replacements[replacement.artifact_id] = replacement
                    refresh_cursor = refreshed.next_cursor
                    if refresh_cursor is None:
                        break
                results = [replacements.get(r.artifact_id, r) if r.state == "refresh_required" else r for r in results]
            for result in results:
                if result.state == "refresh_required":
                    result.state = "failed"
                incomplete |= result.state in ("pending", "unavailable", "failed")
                log.write(result.model_dump_json() + "\n")
                if on_result is not None:
                    on_result(result)
            log.flush()
            os.fsync(log.fileno())
            cursor = page.next_cursor
            if cursor is None:
                break
    return not incomplete
