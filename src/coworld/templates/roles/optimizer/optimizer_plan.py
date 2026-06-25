from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field

HTTP_USER_AGENT = "coworld-optimizer-template/0.1"


class OptimizerPlan(BaseModel):
    optimizer_id: str
    coworld_manifest_uri: str
    recommendations: list[str] = Field(default_factory=list)


def write_data(uri: str, data: bytes) -> None:
    parsed = urlparse(uri)
    if parsed.scheme in ("http", "https"):
        request = Request(uri, data=data, method="PUT")
        request.add_header("Content-Type", "application/json")
        request.add_header("User-Agent", HTTP_USER_AGENT)
        with urlopen(request, timeout=60):
            return
    if parsed.scheme == "file":
        path = Path(unquote(parsed.path))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return
    if parsed.scheme == "":
        path = Path(uri)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return
    raise ValueError(f"Unsupported URI for write_data: {uri}")


def build_plan() -> OptimizerPlan:
    return OptimizerPlan(
        optimizer_id=os.environ["COGAME_OPTIMIZER_ID"],
        coworld_manifest_uri=os.environ["COWORLD_MANIFEST_URI"],
        recommendations=[
            "Run a baseline local episode.",
            "Generate a reporter output, grade, and diagnosis for the baseline episode.",
            "Change one policy behavior at a time and compare against the baseline.",
        ],
    )


def main() -> None:
    plan = build_plan()
    write_data(
        os.environ["COGAME_OPTIMIZER_OUTPUT_URI"],
        f"{json.dumps(plan.model_dump(mode='json'), indent=2)}\n".encode("utf-8"),
    )


if __name__ == "__main__":
    main()
