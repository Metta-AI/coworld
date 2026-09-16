from __future__ import annotations

import json
import subprocess
from pathlib import Path

from coworld.manifest.v0.model import V0Manifest
from coworld.manifest.v1.model import V1Manifest
from coworld.types import coworld_episode_request_schema, coworld_manifest_schema

PACKAGE_ROOT = Path(__file__).resolve().parent.parent / "src" / "coworld"
RUNNER_ROOT = PACKAGE_ROOT / "runner"
MANIFEST_ROOT = PACKAGE_ROOT / "manifest"


def main() -> None:
    schemas = {
        PACKAGE_ROOT / "coworld_manifest_schema.json": coworld_manifest_schema(),
        MANIFEST_ROOT / "v0" / "schema.json": V0Manifest.model_json_schema(by_alias=True),
        MANIFEST_ROOT / "v1" / "schema.json": V1Manifest.model_json_schema(by_alias=True),
        RUNNER_ROOT / "episode_request_schema.json": coworld_episode_request_schema(),
    }
    for path, schema in schemas.items():
        path.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")

    repo_root = PACKAGE_ROOT.parents[3]
    subprocess.run(
        [
            str(repo_root / "node_modules/.bin/oxfmt"),
            "--config",
            str(repo_root / ".oxfmtrc.json"),
            "--write",
            *(str(p) for p in schemas),
        ],
        cwd=repo_root,
        check=True,
    )


if __name__ == "__main__":
    main()
