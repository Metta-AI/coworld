from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import BaseModel, TypeAdapter

from coworld.schema_validation import load_json_object
from coworld.types import (
    CoworldCertificationFixture,
    CoworldCertificationPlayer,
    CoworldDocPage,
    CoworldDocs,
    CoworldEpisodeJobSpec,
    CoworldGameManifest,
    CoworldManifest,
    CoworldManifestRoleSpec,
    CoworldPromo,
    CoworldProtocolDocs,
    CoworldReplayViewer,
    CoworldReporterPlatformReference,
    CoworldReporterWasmReference,
    CoworldResourceLimits,
    CoworldResourceRequests,
    CoworldRunnableResources,
    CoworldRunnableSpec,
    CoworldTextDoc,
    CoworldUriDoc,
    CoworldVariant,
    coworld_manifest_schema,
)

FIXTURE_ROOT = Path(__file__).parent / "manifest_compatibility"
ALL_FIELDS_MANIFEST = FIXTURE_ROOT / "all_fields_manifest.json"
MINIMAL_MANIFEST = FIXTURE_ROOT / "minimal_manifest.json"
MANIFEST_SCHEMA = coworld_manifest_schema()
Draft202012Validator.check_schema(MANIFEST_SCHEMA)
MANIFEST_VALIDATOR = Draft202012Validator(MANIFEST_SCHEMA, format_checker=FormatChecker())
JSON_OBJECT = TypeAdapter(dict[str, Any])


def assert_covers_all_fields(value: dict[str, Any], model: type[BaseModel]) -> None:
    expected = {field.alias or name for name, field in model.model_fields.items()}
    assert set(value) == expected


def test_all_fields_fixture_covers_every_manifest_model_field() -> None:
    manifest = JSON_OBJECT.validate_python(load_json_object(ALL_FIELDS_MANIFEST))

    assert_covers_all_fields(manifest, CoworldManifest)
    assert_covers_all_fields(manifest["game"], CoworldGameManifest)
    assert_covers_all_fields(manifest["game"]["runnable"], CoworldRunnableSpec)
    assert_covers_all_fields(manifest["game"]["runnable"]["resources"], CoworldRunnableResources)
    assert_covers_all_fields(manifest["game"]["runnable"]["resources"]["requests"], CoworldResourceRequests)
    assert_covers_all_fields(manifest["game"]["runnable"]["resources"]["limits"], CoworldResourceLimits)
    assert_covers_all_fields(manifest["game"]["protocols"], CoworldProtocolDocs)
    assert_covers_all_fields(manifest["game"]["protocols"]["player"], CoworldTextDoc)
    assert_covers_all_fields(manifest["game"]["protocols"]["global"], CoworldUriDoc)
    assert_covers_all_fields(manifest["game"]["docs"], CoworldDocs)
    assert_covers_all_fields(manifest["game"]["docs"]["readme"], CoworldTextDoc)
    assert_covers_all_fields(manifest["game"]["docs"]["pages"][0], CoworldDocPage)
    assert_covers_all_fields(manifest["game"]["docs"]["pages"][0]["content"], CoworldUriDoc)
    assert_covers_all_fields(manifest["game"]["promo"], CoworldPromo)
    assert_covers_all_fields(manifest["game"]["replay_viewer"], CoworldReplayViewer)
    assert_covers_all_fields(manifest["player"][0], CoworldManifestRoleSpec)
    assert_covers_all_fields(manifest["reporter"][0], CoworldReporterPlatformReference)
    assert_covers_all_fields(manifest["reporter"][1], CoworldReporterWasmReference)
    assert_covers_all_fields(manifest["variants"][0], CoworldVariant)
    assert_covers_all_fields(manifest["certification"], CoworldCertificationFixture)
    assert_covers_all_fields(manifest["certification"]["players"][0], CoworldCertificationPlayer)


@pytest.mark.parametrize("fixture_path", [ALL_FIELDS_MANIFEST, MINIMAL_MANIFEST], ids=lambda path: path.stem)
def test_golden_manifest_remains_runtime_compatible(fixture_path: Path) -> None:
    raw_manifest = load_json_object(fixture_path)
    MANIFEST_VALIDATOR.validate(raw_manifest)
    manifest = CoworldManifest.model_validate(raw_manifest)

    runner_spec = CoworldEpisodeJobSpec(
        manifest=manifest,
        game_config=manifest.variants[0].game_config,
        players=[manifest.player[0]],
    )
    dumped_runner_spec = runner_spec.model_dump(mode="json", by_alias=True, exclude_none=True)

    CoworldEpisodeJobSpec.model_validate(dumped_runner_spec)
    dumped_manifest = dumped_runner_spec["manifest"]
    CoworldManifest.model_validate(dumped_manifest)
    MANIFEST_VALIDATOR.validate(dumped_manifest)
    if fixture_path == MINIMAL_MANIFEST:
        assert "tags" not in dumped_manifest
