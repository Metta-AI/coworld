from __future__ import annotations

import json
import shutil
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

    # The repo-wide //:prettier_test check formats these tracked JSON files, so
    # emit prettier-compatible output here to keep regeneration in sync with the
    # check. prettier only reflows whitespace; the staleness test
    # (test_generated_schema_files_match_types) compares parsed content, so this
    # stays consistent with the generator output.
    prettier = shutil.which("prettier") or shutil.which("bunx")
    args = [prettier] if prettier and Path(prettier).name == "prettier" else [prettier, "prettier"]
    subprocess.run([*args, "--write", *(str(p) for p in schemas)], check=True)


if __name__ == "__main__":
    main()
