"""Tests for the Log Contract v1 manifest hints and the `coworld certify` richness tier.

See docs/surfaces/logs.md and packages/coworld/src/coworld/docs/artifacts/EVENTS.md for the
contract these hints and tiers document.
"""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from coworld.certifier import compute_log_richness, load_coworld_package
from coworld.manifest import validate_upload_manifest
from coworld.types import CoworldGameLog, CoworldLogPanel, CoworldManifest

FIXTURES = Path(__file__).parent / "manifest_versions"
PAINTARENA_TEMPLATE = (
    Path(__file__).parents[1] / "src" / "coworld" / "examples" / "paintarena" / "coworld_manifest_template.json"
)


def _minimal_manifest_data(
    *,
    log: dict[str, Any] | None = None,
    extra_results_properties: dict[str, Any] | None = None,
) -> dict[str, Any]:
    results_schema: dict[str, Any] = {"type": "object", "properties": {}, "required": []}
    if extra_results_properties:
        results_schema["properties"].update(extra_results_properties)
    data: dict[str, Any] = {
        "game": {
            "name": "richness-test",
            "version": "1.0.0",
            "description": "Minimal manifest for Log richness tests.",
            "owner": "coworld@example.com",
            "config_schema": {},
            "results_schema": results_schema,
            "runnable": {"type": "game", "image": "game"},
            "protocols": {"player": {"type": "text", "value": "p"}, "global": {"type": "text", "value": "g"}},
            "docs": {"readme": {"type": "text", "value": "Readme"}},
        },
        "player": [{"type": "player", "id": "p", "name": "Player", "description": "Player.", "image": "player"}],
        "variants": [{"id": "default", "name": "Default", "description": "Default.", "game_config": {}}],
        "certification": {"game_config": {}, "players": [{"player_id": "p"}]},
    }
    if log is not None:
        data["game"]["log"] = log
    return data


def test_compute_log_richness_is_tier_0_with_no_hints() -> None:
    manifest = CoworldManifest.model_validate(_minimal_manifest_data())

    tier, reason = compute_log_richness(manifest)

    assert tier == 0
    assert "events.json" in reason
    assert "EVENTS.md" in reason


def test_compute_log_richness_is_tier_2_from_game_log_hints() -> None:
    manifest = CoworldManifest.model_validate(
        _minimal_manifest_data(log={"objective": "Score more than your opponent."})
    )

    tier, reason = compute_log_richness(manifest)

    assert tier == 2
    assert "game.log hints declared" in reason


def test_compute_log_richness_is_tier_2_from_results_schema_x_display() -> None:
    manifest = CoworldManifest.model_validate(
        _minimal_manifest_data(
            extra_results_properties={
                "damage_dealt": {"type": "number", "x-display": {"unit": "hp", "higher_is_better": True}}
            }
        )
    )

    tier, reason = compute_log_richness(manifest)

    assert tier == 2
    assert "x-display on damage_dealt" in reason


def test_compute_log_richness_reports_both_reasons_when_both_present() -> None:
    manifest = CoworldManifest.model_validate(
        _minimal_manifest_data(
            log={"objective": "Score more than your opponent."},
            extra_results_properties={"damage_dealt": {"type": "number", "x-display": {"unit": "hp"}}},
        )
    )

    tier, reason = compute_log_richness(manifest)

    assert tier == 2
    assert "game.log hints declared" in reason
    assert "x-display on damage_dealt" in reason


def test_compute_log_richness_ignores_x_display_shaped_values_that_are_not_dicts() -> None:
    # A results_schema.properties entry that is not itself an object (malformed, but the
    # validator only checks the manifest's own JSON Schema shape, not every property's
    # internal shape) must not raise -- richness is informational and never fails certify.
    manifest = CoworldManifest.model_validate(_minimal_manifest_data())
    manifest.game.results_schema["properties"]["weird"] = "not-a-dict"

    tier, _reason = compute_log_richness(manifest)

    assert tier == 0


@pytest.mark.parametrize(
    ("version", "expected_tier"),
    [("v0", 2), ("v1", 2)],
)
def test_log_contract_fixture_certifies_at_tier_2(version: str, expected_tier: int) -> None:
    fixture_path = FIXTURES / version / "log_contract_manifest.json"

    validated = validate_upload_manifest(json.loads(fixture_path.read_text()))
    assert validated.api_version == f"coworld.softmax.com/{version}"

    package = load_coworld_package(fixture_path)
    tier, reason = compute_log_richness(package.manifest)

    assert tier == expected_tier
    assert "game.log hints declared" in reason
    assert "x-display on damage_dealt" in reason


def test_paintarena_example_certifies_at_tier_0() -> None:
    """examples/paintarena declares no Log Contract v1 hints, so it reports tier 0.

    `load_coworld_package` never touches Docker (image reachability is a separate certifier
    step), so the build-time `{{...}}` placeholders only need to be valid strings, not
    resolvable images.
    """
    template = json.loads(PAINTARENA_TEMPLATE.read_text())
    text = re.sub(r"\{\{[A-Z0-9_]+\}\}", "placeholder:latest", json.dumps(template))
    manifest = json.loads(text)
    manifest["game"]["version"] = "1.0.0"

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
        json.dump(manifest, handle)
        manifest_path = Path(handle.name)

    package = load_coworld_package(manifest_path)
    tier, reason = compute_log_richness(package.manifest)

    assert tier == 0
    assert "events.json" in reason


def test_game_log_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        CoworldGameLog.model_validate({"objective": "Win.", "unexpected": "nope"})


def test_game_log_accepts_full_shape() -> None:
    log = CoworldGameLog.model_validate(
        {
            "agent_label_field": "agent",
            "team_field": "team",
            "objective": "Control more territory than every other team.",
            "panels": [{"title": "Combat", "kinds": ["attack", "kill"]}],
        }
    )

    assert log.agent_label_field == "agent"
    assert log.team_field == "team"
    assert log.panels == [CoworldLogPanel(title="Combat", kinds=["attack", "kill"])]


def test_game_log_defaults_are_all_absent() -> None:
    log = CoworldGameLog.model_validate({})

    assert log.agent_label_field is None
    assert log.team_field is None
    assert log.objective is None
    assert log.panels == []


def test_log_panel_requires_at_least_one_kind() -> None:
    with pytest.raises(ValidationError):
        CoworldLogPanel.model_validate({"title": "Combat", "kinds": []})


def test_log_panel_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        CoworldLogPanel.model_validate({"title": "Combat", "kinds": ["attack"], "extra": True})
