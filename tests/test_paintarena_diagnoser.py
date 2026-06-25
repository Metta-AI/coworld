from __future__ import annotations

import json
import zipfile
from collections.abc import Callable
from pathlib import Path

import pytest

from coworld.examples.paintarena.diagnoser import paint_arena_diagnoser as diagnoser
from coworld.examples.paintarena.shared.supporting_role_io import ZIP_ENTRY_MTIME


def test_paintarena_diagnoser_writes_markdown_and_findings_zip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    paint_arena_episode_bundle_path: Callable[[list[int], int, int], Path],
) -> None:
    bundle_path = paint_arena_episode_bundle_path([40, 38], 10, 8)
    diagnosis_path = tmp_path / "diagnosis.zip"
    monkeypatch.setenv("COGAME_EPISODE_BUNDLE_URI", bundle_path.as_uri())
    monkeypatch.setenv("COGAME_TARGET_POLICY_URI", "policy://paintarena-target")
    monkeypatch.setenv("COGAME_DIAGNOSIS_URI", diagnosis_path.as_uri())

    findings = diagnoser.run(diagnoser.load_diagnoser_inputs())

    assert findings.score == 0.025
    with zipfile.ZipFile(diagnosis_path) as bundle:
        assert bundle.namelist() == ["manifest.json", "diagnosis.md", "findings.json"]
        assert [info.date_time for info in bundle.infolist()] == [ZIP_ENTRY_MTIME, ZIP_ENTRY_MTIME, ZIP_ENTRY_MTIME]
        manifest = json.loads(bundle.read("manifest.json"))
        diagnosis = bundle.read("diagnosis.md").decode("utf-8")
        findings_json = json.loads(bundle.read("findings.json"))

    assert manifest == {
        "diagnoser_id": "paint-arena-diagnoser",
        "render": "diagnosis.md",
        "findings": "findings.json",
    }
    assert "policy://paintarena-target" in diagnosis
    assert findings_json["target_policy_uri"] == "policy://paintarena-target"
    assert findings_json["score"] == 0.025
    assert findings_json["winner_slot"] == 0
