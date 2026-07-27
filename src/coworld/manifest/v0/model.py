"""Coworld manifest v0.

V0 and the runtime model intentionally alias today's ``CoworldManifest`` to
avoid duplicating the current model. On the first schema change that must not
apply to v0, copy the affected class or classes into this module and freeze
them here. Runtime evolution after that point belongs in the runtime model, and
compatibility belongs in ``converter.py``.
"""

from coworld.types import CoworldManifest as V0Manifest

__all__ = ["V0Manifest"]
