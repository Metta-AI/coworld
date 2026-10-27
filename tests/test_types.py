from __future__ import annotations

import json
from pathlib import Path

from coworld.manifest.v0.model import V0Manifest
from coworld.manifest.v1.model import V1Manifest
from coworld.types import (
    coworld_episode_request_schema,
    coworld_manifest_schema,
)


def test_generated_schema_files_match_types() -> None:
    package_dir = Path(__file__).parents[1] / "src" / "coworld"

    assert json.loads((package_dir / "coworld_manifest_schema.json").read_text(encoding="utf-8")) == (
        coworld_manifest_schema()
    )
    assert json.loads((package_dir / "manifest" / "v0" / "schema.json").read_text(encoding="utf-8")) == (
        V0Manifest.model_json_schema(by_alias=True)
    )
    assert json.loads((package_dir / "manifest" / "v1" / "schema.json").read_text(encoding="utf-8")) == (
        V1Manifest.model_json_schema(by_alias=True)
    )
    assert json.loads((package_dir / "runner" / "episode_request_schema.json").read_text(encoding="utf-8")) == (
        coworld_episode_request_schema()
    )
