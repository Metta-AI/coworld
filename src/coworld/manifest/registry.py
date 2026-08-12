"""Manifest-version registry and the only author-to-runtime conversion boundary."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Callable, Literal, TypeAlias

from pydantic import BaseModel, TypeAdapter

from coworld.manifest.runtime import RuntimeManifest
from coworld.manifest.v0.converter import to_runtime as v0_to_runtime
from coworld.manifest.v0.model import V0Manifest, V0StoredManifest
from coworld.manifest.v1.converter import to_runtime as v1_to_runtime
from coworld.manifest.v1.model import COWORLD_MANIFEST_V1, V1Manifest

COWORLD_MANIFEST_V0 = "coworld.softmax.com/v0"
ManifestVersion: TypeAlias = Literal["coworld.softmax.com/v0", "coworld.softmax.com/v1"]


@dataclass(frozen=True)
class _ManifestReader:
    model: type[BaseModel]
    converter: Callable[[Any], RuntimeManifest]
    # Stored-read model: same contract plus lifts for historical shapes that
    # predate the authoring contract (v0 only today). Uploads never use it.
    stored_model: type[BaseModel]


@dataclass(frozen=True)
class ValidatedManifest:
    api_version: ManifestVersion
    schema_hash: str
    runtime_manifest: RuntimeManifest


_READERS: dict[ManifestVersion, _ManifestReader] = {
    COWORLD_MANIFEST_V0: _ManifestReader(V0Manifest, v0_to_runtime, stored_model=V0StoredManifest),
    COWORLD_MANIFEST_V1: _ManifestReader(V1Manifest, v1_to_runtime, stored_model=V1Manifest),
}
_VERSION_ADAPTER = TypeAdapter(ManifestVersion)


def _manifest_version(document: dict[str, Any]) -> ManifestVersion:
    if "apiVersion" not in document:
        return COWORLD_MANIFEST_V0
    return _VERSION_ADAPTER.validate_python(document["apiVersion"])


def manifest_schema_hash(api_version: ManifestVersion) -> str:
    schema = _READERS[api_version].model.model_json_schema(by_alias=True, ref_template="#/$defs/{model}")
    encoded = json.dumps(schema, sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def validate_upload_manifest(document: dict[str, Any]) -> ValidatedManifest:
    """Strictly validate one upload and convert it to the runtime contract."""
    api_version = _manifest_version(document)
    reader = _READERS[api_version]
    author_manifest = reader.model.model_validate(document)
    return ValidatedManifest(
        api_version=api_version,
        schema_hash=manifest_schema_hash(api_version),
        runtime_manifest=reader.converter(author_manifest),
    )


def to_runtime_manifest(api_version: str, document: dict[str, Any]) -> RuntimeManifest:
    """Read a certified stored manifest, tolerating newer fields at every model depth."""
    version = _VERSION_ADAPTER.validate_python(api_version)
    reader = _READERS[version]
    author_manifest = reader.stored_model.model_validate(document, extra="ignore")
    return reader.converter(author_manifest)


def read_downloaded_manifest(document: dict[str, Any]) -> RuntimeManifest:
    """Read a platform-served manifest document (e.g. `coworld download` output).

    Within one apiVersion new manifest fields are additive by contract, so a consumer
    tolerates fields newer than its models instead of rejecting the server's output.
    """
    return to_runtime_manifest(_manifest_version(document), document)
