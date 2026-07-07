from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field

HTTP_USER_AGENT = "coworld-paintarena-optimizer/0.1"
JSON_CONTENT_TYPE = "application/json"


class OptimizerInputs(BaseModel):
    coworld_manifest_uri: str
    optimizer_output_uri: str
    optimizer_id: str
    policy_workspace_uri: str | None = None
    report_uris: list[str] = Field(default_factory=list)
    grader_output_uris: list[str] = Field(default_factory=list)
    diagnoser_output_uris: list[str] = Field(default_factory=list)


class OptimizerInputCounts(BaseModel):
    reports: int
    grader_outputs: int
    diagnoser_outputs: int


class OptimizerCoworldGame(BaseModel):
    name: str


class OptimizerCoworldManifest(BaseModel):
    game: OptimizerCoworldGame


class PaintArenaOptimizerPlan(BaseModel):
    optimizer_id: str
    coworld_name: str
    policy_workspace_uri: str | None
    input_counts: OptimizerInputCounts
    recommendations: list[str]


def env_uri_list(name: str) -> list[str]:
    return [uri.strip() for uri in os.environ.get(name, "").split(",") if uri.strip()]


def load_optimizer_inputs() -> OptimizerInputs:
    return OptimizerInputs(
        coworld_manifest_uri=os.environ["COWORLD_MANIFEST_URI"],
        optimizer_output_uri=os.environ["COGAME_OPTIMIZER_OUTPUT_URI"],
        optimizer_id=os.environ["COGAME_OPTIMIZER_ID"],
        policy_workspace_uri=os.environ.get("COGAME_POLICY_WORKSPACE_URI"),
        report_uris=env_uri_list("COGAME_REPORT_URIS"),
        grader_output_uris=env_uri_list("COGAME_GRADER_OUTPUT_URIS"),
        diagnoser_output_uris=env_uri_list("COGAME_DIAGNOSER_OUTPUT_URIS"),
    )


def read_data(uri: str) -> bytes:
    parsed = urlparse(uri)
    if parsed.scheme in ("http", "https"):
        request = Request(uri, headers={"User-Agent": HTTP_USER_AGENT})
        with urlopen(request, timeout=30) as response:
            return response.read()
    if parsed.scheme == "file":
        return Path(unquote(parsed.path)).read_bytes()
    if parsed.scheme == "":
        return Path(uri).read_bytes()
    raise ValueError(f"Unsupported URI for read_data: {uri}")


def write_data(uri: str, data: bytes) -> None:
    parsed = urlparse(uri)
    if parsed.scheme in ("http", "https"):
        request = Request(uri, data=data, method="PUT")
        request.add_header("Content-Type", JSON_CONTENT_TYPE)
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


def build_plan(manifest: OptimizerCoworldManifest, inputs: OptimizerInputs) -> PaintArenaOptimizerPlan:
    recommendations = [
        "Run the bundled sweep-painter baseline and the target policy on the default PaintArena variant.",
        "Compare painted_tiles and per-frame territory ownership from episode results and replay stats.",
    ]
    if inputs.report_uris:
        recommendations.append("Use the supplied report artifacts to identify low-paint-share intervals.")
    else:
        recommendations.append("Run a platform reporter over recent PaintArena episodes before iterating.")
    if inputs.diagnoser_output_uris:
        recommendations.append("Apply supplied diagnoser advice before changing exploration or movement heuristics.")
    if inputs.grader_output_uris:
        recommendations.append("Prioritize changes that improve grader-selected episodes before broad retesting.")
    if inputs.policy_workspace_uri is None:
        recommendations.append("Create a policy workspace from the PaintArena starter before writing code changes.")

    return PaintArenaOptimizerPlan(
        optimizer_id=inputs.optimizer_id,
        coworld_name=manifest.game.name,
        policy_workspace_uri=inputs.policy_workspace_uri,
        input_counts=OptimizerInputCounts(
            reports=len(inputs.report_uris),
            grader_outputs=len(inputs.grader_output_uris),
            diagnoser_outputs=len(inputs.diagnoser_output_uris),
        ),
        recommendations=recommendations,
    )


def run(inputs: OptimizerInputs) -> PaintArenaOptimizerPlan:
    manifest = OptimizerCoworldManifest.model_validate(json.loads(read_data(inputs.coworld_manifest_uri)))
    plan = build_plan(manifest, inputs)
    write_data(inputs.optimizer_output_uri, f"{plan.model_dump_json(indent=2)}\n".encode("utf-8"))
    return plan


def main() -> None:
    run(load_optimizer_inputs())


if __name__ == "__main__":
    main()
