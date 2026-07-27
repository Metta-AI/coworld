"""Canonical manifest used by runtime code.

The runtime model and v0 intentionally alias today's ``CoworldManifest`` to
avoid duplicating the current model. On the first schema change that must not
apply to v0, copy the affected class or classes into ``v0/model.py`` and freeze
them there. Runtime code may then evolve independently; the version converters
remain the only bridge from stored author schemas to this model.
"""

from coworld.types import CoworldManifest as RuntimeManifest

__all__ = ["RuntimeManifest"]
