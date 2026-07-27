"""Convert v0 author manifests to the canonical runtime model."""

from coworld.manifest.runtime import RuntimeManifest
from coworld.manifest.v0.model import V0Manifest


def to_runtime(manifest: V0Manifest) -> RuntimeManifest:
    """Convert a validated v0 manifest to the runtime contract."""
    return manifest
