from __future__ import annotations

import json
from pathlib import Path

from coworld.types import coworld_episode_request_schema, coworld_manifest_schema

PACKAGE_ROOT = Path(__file__).resolve().parent.parent / "src" / "coworld"
RUNNER_ROOT = PACKAGE_ROOT / "runner"


def main() -> None:
    schemas = {
        PACKAGE_ROOT / "coworld_manifest_schema.json": coworld_manifest_schema(),
        RUNNER_ROOT / "episode_request_schema.json": coworld_episode_request_schema(),
    }
    for path, schema in schemas.items():
        path.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
