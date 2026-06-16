"""Reporter episode-input reader.

A reporter receives a ``COGAME_REPORT_REQUEST`` JSON payload whose
``episodes`` entries contain a manifest, presigned artifact refs, and
small inline JSON payloads. The reader fetches artifact refs lazily via
:func:`reporter_sdk.io.read_uri`, caches bytes by token, decompresses
zlib-encoded refs, and exposes the same token accessors reporters used
for zip-backed episode bundles.
"""

from __future__ import annotations

import json
import zlib
from typing import Any

from .io import read_uri
from .protocol import ReporterArtifactRef, ReporterEpisodeInput, ReporterEpisodeManifest

BundleInnerManifest = ReporterEpisodeManifest


class BundleReader:
    """Reads one ``ReporterEpisodeInput`` through bundle-style token accessors."""

    def __init__(self, episode: ReporterEpisodeInput) -> None:
        self._episode = episode
        self._manifest = episode.manifest
        self._cache: dict[str, bytes] = {}

    def inner_manifest(self) -> BundleInnerManifest:
        return self._manifest

    def _artifact_ref(self, token: str) -> ReporterArtifactRef:
        path = self._manifest.files[token]
        if not isinstance(path, str):
            raise TypeError(
                f"token {token!r} maps to a multi-file entry ({type(path).__name__}); "
                "this reader only handles single-file tokens"
            )
        ref = getattr(self._episode.artifacts, token)
        assert isinstance(ref, ReporterArtifactRef), f"episode input has no artifact ref for token {token!r}"
        return ref

    def read_bytes(self, token: str) -> bytes:
        if token in self._cache:
            return self._cache[token]
        if token == "error_info":
            error_info = self._episode.inline_json.error_info
            assert error_info is not None, "episode input has no inline error_info"
            payload = json.dumps(error_info.model_dump(exclude_none=True), indent=2).encode("utf-8")
        else:
            ref = self._artifact_ref(token)
            payload = read_uri(ref.uri)
            if ref.encoding == "zlib":
                payload = zlib.decompress(payload)
        self._cache[token] = payload
        return payload

    def read_bytes_optional(self, token: str) -> bytes | None:
        if token not in self._manifest.include:
            return None
        return self.read_bytes(token)

    def read_json(self, token: str) -> Any:
        return json.loads(self.read_bytes(token))

    def read_json_optional(self, token: str) -> Any | None:
        raw = self.read_bytes_optional(token)
        return None if raw is None else json.loads(raw)

    def close(self) -> None:
        self._cache.clear()

    def __enter__(self) -> "BundleReader":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
