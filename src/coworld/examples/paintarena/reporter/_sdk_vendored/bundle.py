"""Episode-bundle reader.

A reporter receives one ``COGAME_EPISODE_BUNDLE_URI`` pointing at a zip
whose root holds a ``manifest.json`` mapping named tokens (``results``,
``replay``, ``config``, ``metadata``, ``game_logs``, ``player_logs``,
``error_info``) to their paths inside the zip. The reader fetches the
zip via :func:`reporter_sdk.io.read_uri`, parses the inner manifest, and
exposes typed accessors keyed by token name.

Schema mirrors metta's ``packages/coworld/src/coworld/EPISODE_BUNDLE_README.md``.
``BundleInnerManifest`` allows extra fields so forward-extension keys
the metta bundler may add (for example, an ``episode_id`` carrier) do
not trip validation.
"""

from __future__ import annotations

import io
import json
import zipfile
from typing import Any

from pydantic import BaseModel, Field

from .io import read_uri


class BundleInnerManifest(BaseModel):
    """The ``manifest.json`` at the root of every episode bundle zip.

    ``ereq_id`` identifies the upstream episode request. ``status`` is
    ``"success"`` for a normal episode and ``"failed"`` (with an
    ``error_info`` token in ``files``) for a failed one. ``include`` is
    the set of tokens actually delivered after access-control filtering;
    optional tokens absent from ``include`` should be skipped by readers
    even if a token-to-path mapping happens to exist in ``files``.
    ``files`` maps token name to in-zip path (string) for single-file
    tokens, or to a dict for multi-file tokens like ``game_logs``.
    """

    ereq_id: str
    status: str = "success"
    include: list[str] = Field(default_factory=list)
    files: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "allow"}


class BundleReader:
    """Opens an episode bundle zip from a URI, parses its inner
    ``manifest.json``, and exposes typed accessors for its named tokens.

    Tokens map to entries inside the zip via ``manifest.json::files``.
    :meth:`read_bytes` / :meth:`read_json` require the token to be
    present; :meth:`read_bytes_optional` / :meth:`read_json_optional`
    return ``None`` when the token isn't in ``manifest.include`` so
    callers can transparently handle access-controlled bundles where a
    token may have been filtered out.

    Multi-file tokens (where ``files[token]`` is a dict) are not handled
    by this reader; callers that need them should subclass and reach for
    the underlying zip themselves.
    """

    def __init__(self, bundle_uri: str) -> None:
        self._bytes = read_uri(bundle_uri)
        self._zf = zipfile.ZipFile(io.BytesIO(self._bytes))
        raw = json.loads(self._zf.read("manifest.json"))
        self._manifest = BundleInnerManifest.model_validate(raw)

    def inner_manifest(self) -> BundleInnerManifest:
        return self._manifest

    def _token_path(self, token: str) -> str:
        path = self._manifest.files.get(token)
        if path is None:
            raise KeyError(f"bundle has no entry for token {token!r}")
        if not isinstance(path, str):
            raise TypeError(
                f"token {token!r} maps to a multi-file entry ({type(path).__name__}); "
                "this reader only handles single-file tokens"
            )
        return path

    def read_bytes(self, token: str) -> bytes:
        return self._zf.read(self._token_path(token))

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
        self._zf.close()

    def __enter__(self) -> "BundleReader":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
