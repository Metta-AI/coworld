"""Coworld manifest v1 author contract."""

from typing import Final, Literal

from pydantic import Field

from coworld.manifest.v0.model import V0Manifest

COWORLD_MANIFEST_V1: Final = "coworld.softmax.com/v1"


class V1Manifest(V0Manifest):
    """V0 with an explicit author-schema version tag."""

    api_version: Literal["coworld.softmax.com/v1"] = Field(alias="apiVersion")
