"""Convert v1 author manifests to the canonical runtime model."""

from coworld.manifest.runtime import RuntimeManifest
from coworld.manifest.v1.model import V1Manifest


def to_runtime(manifest: V1Manifest) -> RuntimeManifest:
    """Convert a validated v1 manifest to the runtime contract."""
    return RuntimeManifest.model_validate(manifest.model_dump(exclude={"api_version"}))
