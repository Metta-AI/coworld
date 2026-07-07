from __future__ import annotations

import json
from pathlib import Path

import pytest

from coworld.examples.paintarena.optimizer import paint_arena_optimizer as optimizer


def test_paintarena_optimizer_writes_plan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest_uri = _materialized_manifest(tmp_path).as_uri()
    output_path = tmp_path / "optimizer-plan.json"
    monkeypatch.setenv("COWORLD_MANIFEST_URI", manifest_uri)
    monkeypatch.setenv("COGAME_OPTIMIZER_ID", "paint-arena-reference-optimizer")
    monkeypatch.setenv("COGAME_OPTIMIZER_OUTPUT_URI", output_path.as_uri())
    monkeypatch.setenv("COGAME_POLICY_WORKSPACE_URI", (tmp_path / "policy").as_uri())
    monkeypatch.setenv("COGAME_REPORT_URIS", "file:///reports/summary.zip,file:///reports/stats.parquet")
    monkeypatch.setenv("COGAME_GRADER_OUTPUT_URIS", "file:///grades/episode.json")
    monkeypatch.setenv("COGAME_DIAGNOSER_OUTPUT_URIS", "file:///diagnoses/policy.json")

    plan = optimizer.run(optimizer.load_optimizer_inputs())
    artifact = json.loads(output_path.read_text(encoding="utf-8"))

    assert plan.coworld_name == "paintarena"
    assert artifact["optimizer_id"] == "paint-arena-reference-optimizer"
    assert artifact["coworld_name"] == "paintarena"
    assert artifact["input_counts"] == {"reports": 2, "grader_outputs": 1, "diagnoser_outputs": 1}
    assert artifact["recommendations"] == [
        "Run the bundled sweep-painter baseline and the target policy on the default PaintArena variant.",
        "Compare painted_tiles and per-frame territory ownership from episode results and replay stats.",
        "Use the supplied report artifacts to identify low-paint-share intervals.",
        "Apply supplied diagnoser advice before changing exploration or movement heuristics.",
        "Prioritize changes that improve grader-selected episodes before broad retesting.",
    ]


def _materialized_manifest(tmp_path: Path) -> Path:
    template_path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "coworld"
        / "examples"
        / "paintarena"
        / "coworld_manifest_template.json"
    )
    manifest = json.loads(template_path.read_text(encoding="utf-8").replace("{{PAINTARENA_IMAGE}}", "paintarena"))
    manifest["game"]["version"] = "0.1.0"
    manifest_path = tmp_path / "coworld_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path
