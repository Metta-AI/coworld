import json
import subprocess

import pytest

from coworld.manifest import schema_check
from coworld.manifest.schema_check import _obvious_narrowings, check_manifest_schema
from coworld.manifest.v0.model import V0Manifest
from coworld.manifest.v1.model import V1Manifest
from coworld.types import coworld_manifest_schema


def test_tampered_prior_declaration_fails_even_with_one_appended(monkeypatch: pytest.MonkeyPatch) -> None:
    """Editing or reordering existing declarations.yaml entries must fail even when
    exactly one new entry is appended — the log is append-only, not length-checked.

    _git is stubbed entirely (no real repo in the Bazel sandbox): the fake base ref
    serves the current generated schemas (so schema_changed is False) and a tampered
    copy of each current declarations file.
    """

    versioned_models = ((schema_check.COWORLD_MANIFEST_V0, V0Manifest), (schema_check.COWORLD_MANIFEST_V1, V1Manifest))
    current_schemas = {
        schema_check.SCHEMA_PATHS[version]: json.dumps(model.model_json_schema(by_alias=True))
        for version, model in versioned_models
    }

    def fake_git(*args: str) -> subprocess.CompletedProcess[str]:
        if args[0] == "rev-parse":
            return subprocess.CompletedProcess(args, 0, "0" * 40, "")
        assert args[0] == "show"
        path = args[1].split(":", 1)[1]
        if path in current_schemas:
            return subprocess.CompletedProcess(args, 0, current_schemas[path], "")
        if path == schema_check.BASE_SCHEMA_PATH:
            return subprocess.CompletedProcess(args, 0, json.dumps(coworld_manifest_schema()), "")
        assert path.endswith("declarations.yaml")
        current_text = (schema_check.REPO_ROOT / path).read_text()
        return subprocess.CompletedProcess(args, 0, current_text.replace("summary:", "summary: TAMPERED", 1), "")

    monkeypatch.setattr(schema_check, "_git", fake_git)

    failures = check_manifest_schema("HEAD")

    assert any("declarations changed but its generated schema did not" in f for f in failures)


def test_obvious_narrowings_detect_required_field() -> None:
    before = {"type": "object", "properties": {"name": {"type": "string"}}}
    after = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    }

    assert _obvious_narrowings(before, after) == ["$: newly required field 'name'"]


def test_missing_comparison_ref_is_actionable() -> None:
    failures = check_manifest_schema("definitely-not-a-git-ref")

    assert len(failures) == 1
    assert "fetch-depth: 0" in failures[0]
