from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from coworld.manifest import (
    COWORLD_MANIFEST_V0,
    COWORLD_MANIFEST_V1,
    ManifestVersion,
    RuntimeManifest,
    to_runtime_manifest,
    validate_upload_manifest,
)
from coworld.types import coworld_manifest_schema

FIXTURES = Path(__file__).parent / "manifest_versions"


def _fixture(version: str, name: str = "minimal_manifest.json") -> dict[str, object]:
    return json.loads((FIXTURES / version / name).read_text())


@pytest.mark.parametrize(
    ("version", "fixture_name"),
    [
        ("v0", "minimal_manifest.json"),
        ("v0", "all_fields_manifest.json"),
        ("v1", "minimal_manifest.json"),
        ("v1", "all_fields_manifest.json"),
    ],
)
def test_version_fixtures_validate_and_convert(version: str, fixture_name: str) -> None:
    document = _fixture(version, fixture_name)

    validated = validate_upload_manifest(document)

    assert isinstance(validated.runtime_manifest, RuntimeManifest)
    assert validated.api_version == f"coworld.softmax.com/{version}"
    assert validated.runtime_manifest.game.name in {"minimal-coworld", "golden-coworld"}


def test_missing_api_version_selects_v0() -> None:
    assert validate_upload_manifest(_fixture("v0")).api_version == COWORLD_MANIFEST_V0


def test_v0_hash_matches_the_existing_certifier_schema_hash() -> None:
    expected = hashlib.sha256(json.dumps(coworld_manifest_schema(), sort_keys=True).encode()).hexdigest()

    assert validate_upload_manifest(_fixture("v0")).schema_hash == expected


def test_v1_requires_its_api_version() -> None:
    document = _fixture("v0")
    document["apiVersion"] = COWORLD_MANIFEST_V1

    assert validate_upload_manifest(document).api_version == COWORLD_MANIFEST_V1


def test_upload_validation_remains_strict() -> None:
    document = _fixture("v1")
    document["futureField"] = True

    with pytest.raises(ValidationError):
        validate_upload_manifest(document)


@pytest.mark.parametrize(
    ("version", "api_version"),
    [("v0", COWORLD_MANIFEST_V0), ("v1", COWORLD_MANIFEST_V1)],
)
def test_stored_read_ignores_unknown_fields_recursively(version: str, api_version: ManifestVersion) -> None:
    document = _fixture(version)
    document["futureField"] = True
    game = document["game"]
    assert isinstance(game, dict)
    game["futureGameField"] = True

    manifest = to_runtime_manifest(api_version, document)

    assert manifest.game.name == "minimal-coworld"


def test_v1_converter_does_not_leak_author_version_into_runtime() -> None:
    runtime = validate_upload_manifest(_fixture("v1")).runtime_manifest

    assert "apiVersion" not in runtime.model_dump(by_alias=True)


@pytest.mark.parametrize("fixture_name", ["minimal_manifest.json", "all_fields_manifest.json"])
def test_v0_and_v1_baselines_convert_to_the_same_runtime(fixture_name: str) -> None:
    v0_runtime = validate_upload_manifest(_fixture("v0", fixture_name)).runtime_manifest
    v1_runtime = validate_upload_manifest(_fixture("v1", fixture_name)).runtime_manifest

    assert v1_runtime == v0_runtime


def _pre_v0_document(*, drop_docs: bool, string_protocols: bool) -> dict[str, object]:
    """A stored-corpus shape from before the current authoring contract."""
    document = _fixture("v0")
    game = document["game"]
    assert isinstance(game, dict)
    if drop_docs:
        del game["docs"]
    else:
        docs = game["docs"]
        assert isinstance(docs, dict)
        del docs["readme"]
    if string_protocols:
        game["protocols"] = {"player": "# Player protocol", "global": "# Global protocol"}
    return document


@pytest.mark.parametrize(
    ("drop_docs", "string_protocols"),
    [(True, False), (False, False), (True, True)],
    ids=["docs-missing", "readme-missing", "docs-missing-and-string-protocols"],
)
def test_stored_read_lifts_pre_v0_shapes(drop_docs: bool, string_protocols: bool) -> None:
    document = _pre_v0_document(drop_docs=drop_docs, string_protocols=string_protocols)
    original = json.dumps(document, sort_keys=True)

    manifest = to_runtime_manifest(COWORLD_MANIFEST_V0, document)

    assert manifest.game.docs.readme.value  # lifted from description
    assert manifest.game.protocols.player.value
    # The raw stored document is never mutated by the lift.
    assert json.dumps(document, sort_keys=True) == original


def test_upload_still_rejects_pre_v0_shapes() -> None:
    document = _pre_v0_document(drop_docs=True, string_protocols=True)

    with pytest.raises(ValidationError):
        validate_upload_manifest(document)
