from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError

from coworld.schema_validation import validate_json_schema
from coworld.types import (
    CoworldEpisodeJobSpec,
    CoworldManifest,
    CoworldRunnableSpec,
    CoworldVariant,
    coworld_episode_request_schema,
    coworld_manifest_schema,
)


def test_variant_does_not_have_parent_id_field() -> None:
    assert "parent_id" not in CoworldVariant.model_fields


def test_variant_rejects_parent_id() -> None:
    with pytest.raises(ValidationError):
        CoworldVariant.model_validate(
            {
                "id": "v1",
                "name": "Variant 1",
                "game_config": {},
                "description": "Variant 1",
                "parent_id": "v0",
            }
        )


def test_runnable_and_manifest_role_fields_are_flat() -> None:
    spec = CoworldRunnableSpec(type="game", image="game", source_url="https://example.com")

    assert spec.source_url == "https://example.com"
    assert set(CoworldRunnableSpec.model_fields) == {"type", "image", "run", "env", "source_url"}


def test_manifest_rejects_wrong_game_runnable_type() -> None:
    schema = coworld_manifest_schema()["$defs"]["CoworldGameManifest"]["properties"]["runnable"]["properties"]["type"]
    assert schema["const"] == "game"
    with pytest.raises(ValidationError, match="game.runnable.type"):
        _manifest(game_type="player")


def test_manifest_rejects_wrong_role_section_type() -> None:
    with pytest.raises(ValidationError, match="player.0.type"):
        _manifest(player_type="reporter")


def test_manifest_rejects_wrong_grader_section_type() -> None:
    manifest = _manifest_data()
    manifest["grader"][0]["type"] = "reporter"

    with pytest.raises(ValidationError, match="grader.0.type"):
        CoworldManifest.model_validate(manifest)


def test_manifest_allows_missing_grader_entries() -> None:
    manifest = _manifest_data()
    del manifest["grader"]

    assert CoworldManifest.model_validate(manifest).grader == []


def test_manifest_allows_empty_grader_entries() -> None:
    manifest = _manifest_data()
    manifest["grader"] = []

    assert CoworldManifest.model_validate(manifest).grader == []


def test_manifest_schema_allows_missing_grader_entries() -> None:
    manifest = _manifest_data()
    del manifest["grader"]

    validate_json_schema(manifest, coworld_manifest_schema())


def test_manifest_schema_allows_empty_grader_entries() -> None:
    manifest = _manifest_data()
    manifest["grader"] = []

    validate_json_schema(manifest, coworld_manifest_schema())


def test_episode_job_players_are_flat_runnable_payloads() -> None:
    manifest = _manifest()
    job = CoworldEpisodeJobSpec(manifest=manifest, game_config={}, players=[manifest.player[0]])

    assert job.model_dump(exclude_defaults=True)["players"] == [
        {"type": "player", "image": "player", "source_url": "https://example.com/player"}
    ]


def test_episode_job_rejects_non_player_runnable() -> None:
    schema = coworld_episode_request_schema()["properties"]["players"]["items"]["properties"]["type"]
    assert schema["const"] == "player"
    with pytest.raises(ValidationError, match="players.0.type"):
        CoworldEpisodeJobSpec(
            manifest=_manifest(),
            game_config={},
            players=[CoworldRunnableSpec(type="reporter", image="reporter")],
        )


def test_manifest_rejects_null_game_docs() -> None:
    manifest = _manifest_data()
    manifest["game"]["docs"] = None

    with pytest.raises(ValidationError, match="game.docs"):
        CoworldManifest.model_validate(manifest)


def test_manifest_rejects_missing_game_docs() -> None:
    manifest = _manifest_data()
    del manifest["game"]["docs"]

    with pytest.raises(ValidationError, match="game.docs"):
        CoworldManifest.model_validate(manifest)


def test_manifest_rejects_empty_game_docs_pages() -> None:
    manifest = _manifest_data()
    manifest["game"]["docs"]["pages"] = []

    _assert_docs_page_error(manifest, rules_count=0, play_count=0)


def test_manifest_rejects_game_docs_pages_without_play_page() -> None:
    manifest = _manifest_data()
    manifest["game"]["docs"]["pages"] = [
        {"id": "rules.md", "title": "rules.md", "content": {"type": "text", "value": "# Rules"}}
    ]

    _assert_docs_page_error(manifest, play_count=0)


def test_manifest_rejects_game_docs_pages_without_rules_page() -> None:
    manifest = _manifest_data()
    manifest["game"]["docs"]["pages"] = [
        {"id": "play_unittest.md", "title": "play_unittest.md", "content": {"type": "text", "value": "# Play"}}
    ]

    _assert_docs_page_error(manifest, rules_count=0)


def test_manifest_rejects_duplicate_required_game_docs_pages() -> None:
    manifest = _manifest_data()
    pages = manifest["game"]["docs"]["pages"]
    pages.append({"id": "rules.md", "title": "rules.md", "content": {"type": "text", "value": "# Other Rules"}})

    _assert_docs_page_error(manifest, rules_count=2)

    manifest = _manifest_data()
    pages = manifest["game"]["docs"]["pages"]
    pages.append(
        {
            "id": "play_advanced.md",
            "title": "play_advanced.md",
            "content": {"type": "text", "value": "# Advanced Play"},
        }
    )

    _assert_docs_page_error(manifest, play_count=2)


@pytest.mark.parametrize(
    "page_id",
    [
        "play_Foo.md",
        "play_-foo.md",
        "play__foo.md",
    ],
)
def test_manifest_rejects_noncanonical_play_page_id(page_id: str) -> None:
    manifest = _manifest_data()
    manifest["game"]["docs"]["pages"][1]["id"] = page_id

    with pytest.raises(ValidationError) as exc_info:
        CoworldManifest.model_validate(manifest)
    message = str(exc_info.value)
    assert page_id in message
    assert "`play_` prefix" in message


@pytest.mark.parametrize(
    "extra_play_id",
    [
        "play_AmongThem.md",
        "play_-foo.md",
        "play__foo.md",
    ],
)
def test_manifest_rejects_extra_noncanonical_play_page_alongside_canonical(extra_play_id: str) -> None:
    manifest = _manifest_data()
    manifest["game"]["docs"]["pages"].append(
        {
            "id": extra_play_id,
            "title": extra_play_id,
            "content": {"type": "text", "value": "# Stale noncanonical play guide"},
        }
    )

    with pytest.raises(ValidationError) as exc_info:
        CoworldManifest.model_validate(manifest)
    message = str(exc_info.value)
    assert extra_play_id in message
    assert "`play_` prefix" in message


def test_manifest_schema_rejects_extra_noncanonical_play_page_alongside_canonical() -> None:
    manifest = _manifest_data()
    manifest["game"]["docs"]["pages"].append(
        {
            "id": "play_AmongThem.md",
            "title": "play_AmongThem.md",
            "content": {"type": "text", "value": "# Stale noncanonical play guide"},
        }
    )

    with pytest.raises(JsonSchemaValidationError):
        validate_json_schema(manifest, coworld_manifest_schema())


def test_manifest_strips_doc_page_id_trailing_newlines() -> None:
    manifest = _manifest_data()
    manifest["game"]["docs"]["pages"][0]["id"] = "rules.md\n"
    manifest["game"]["docs"]["pages"][1]["id"] = "play_unittest.md\r\n"

    typed_manifest = CoworldManifest.model_validate(manifest)

    assert [page.id for page in typed_manifest.game.docs.pages] == ["rules.md", "play_unittest.md"]


def test_manifest_schema_rejects_missing_required_game_docs_pages() -> None:
    manifest = _manifest_data()
    manifest["game"]["docs"]["pages"] = []

    with pytest.raises(JsonSchemaValidationError):
        validate_json_schema(manifest, coworld_manifest_schema())


def test_manifest_schema_rejects_duplicate_required_game_docs_pages() -> None:
    manifest = _manifest_data()
    manifest["game"]["docs"]["pages"].append(
        {
            "id": "play_extra.md",
            "title": "play_extra.md",
            "content": {"type": "text", "value": "# Extra Play"},
        }
    )

    with pytest.raises(JsonSchemaValidationError):
        validate_json_schema(manifest, coworld_manifest_schema())


def test_manifest_accepts_required_game_docs_pages() -> None:
    manifest = CoworldManifest.model_validate(_manifest_data())

    assert [page.id for page in manifest.game.docs.pages] == ["rules.md", "play_unittest.md"]


def test_manifest_schema_accepts_required_game_docs_pages() -> None:
    validate_json_schema(_manifest_data(), coworld_manifest_schema())


def test_manifest_schema_documents_public_fields() -> None:
    schema = coworld_manifest_schema()

    _assert_schema_properties_have_descriptions("CoworldManifest", schema)
    for name, definition in schema["$defs"].items():
        _assert_schema_properties_have_descriptions(name, definition)

    assert "commissioner" not in schema["required"]
    assert "grader" not in schema["required"]
    assert "diagnoser" not in schema["required"]
    assert "optimizer" not in schema["required"]
    role_docs = {
        "game": "docs/roles/GAME.md",
        "player": "docs/roles/PLAYER.md",
        "reporter": "docs/roles/REPORTER.md",
        "commissioner": "docs/roles/COMMISSIONER.md",
        "grader": "docs/roles/GRADER.md",
        "diagnoser": "docs/roles/DIAGNOSER.md",
        "optimizer": "docs/roles/OPTIMIZER.md",
    }
    for section, role_doc in role_docs.items():
        section_schema = schema["properties"][section]
        assert section_schema["x-coworld-role-doc"] == role_doc
        assert f"]({role_doc})" in section_schema["markdownDescription"]
    for section in ("commissioner", "diagnoser", "optimizer"):
        section_schema = schema["properties"][section]
        assert section_schema["x-coworld-future-required"] is True
        assert "intended to become required" in section_schema["$comment"]
    grader_schema = schema["properties"]["grader"]
    assert grader_schema["x-coworld-future-required"] is True
    assert "required by Coworld upload validation" in grader_schema["$comment"]


def test_generated_schema_files_match_types() -> None:
    package_dir = Path(__file__).parents[1] / "src" / "coworld"

    assert json.loads((package_dir / "coworld_manifest_schema.json").read_text(encoding="utf-8")) == (
        coworld_manifest_schema()
    )
    assert json.loads((package_dir / "runner" / "episode_request_schema.json").read_text(encoding="utf-8")) == (
        coworld_episode_request_schema()
    )


def _manifest(game_type: str = "game", player_type: str = "player") -> CoworldManifest:
    return CoworldManifest.model_validate(_manifest_data(game_type=game_type, player_type=player_type))


def _assert_schema_properties_have_descriptions(schema_name: str, schema: dict[str, Any]) -> None:
    missing = [
        f"{schema_name}.{field_name}"
        for field_name, field_schema in schema.get("properties", {}).items()
        if "description" not in field_schema
    ]
    assert missing == []


def _assert_docs_page_error(
    manifest: dict[str, Any],
    *,
    rules_count: int = 1,
    play_count: int = 1,
) -> None:
    assert rules_count != 1 or play_count != 1
    with pytest.raises(ValidationError) as exc_info:
        CoworldManifest.model_validate(manifest)
    message = str(exc_info.value)
    if rules_count != 1:
        assert f"expected exactly one `rules.md` page; found {rules_count}" in message
    if play_count != 1:
        assert (
            f"expected exactly one page matching `play_*.md` (`^play_[a-z0-9][a-z0-9_-]*\\.md$`); found {play_count}"
        ) in message


def _manifest_data(game_type: str = "game", player_type: str = "player") -> dict[str, Any]:
    return {
        "game": {
            "name": "Example",
            "version": "1.0.0",
            "description": "Example Coworld.",
            "owner": "coworld@softmax.com",
            "runnable": {"type": game_type, "image": "game"},
            "config_schema": {},
            "results_schema": {},
            "protocols": {"player": {"type": "text", "value": "p"}, "global": {"type": "text", "value": "g"}},
            "docs": {
                "pages": [
                    {"id": "rules.md", "title": "rules.md", "content": {"type": "text", "value": "# Rules"}},
                    {
                        "id": "play_unittest.md",
                        "title": "play_unittest.md",
                        "content": {"type": "text", "value": "# Play"},
                    },
                ]
            },
        },
        "player": [
            {
                "id": "player",
                "name": "Player",
                "description": "Player.",
                "type": player_type,
                "image": "player",
                "source_url": "https://example.com/player",
            }
        ],
        "reporter": [
            {
                "id": "reporter",
                "name": "Reporter",
                "description": "Reporter.",
                "type": "reporter",
                "image": "reporter",
                "source_url": "https://example.com/reporter",
            }
        ],
        "grader": [
            {
                "id": "default-grader",
                "name": "Default Grader",
                "description": "Default grader stub for unit tests.",
                "type": "grader",
                "image": "ghcr.io/metta-ai/graders-default:latest",
                "source_url": "https://github.com/Metta-AI/graders/tree/main/graders/default/default_grader",
            }
        ],
        "variants": [{"id": "default", "name": "Default", "description": "Default.", "game_config": {}}],
        "certification": {"game_config": {}, "players": [{"player_id": "player"}]},
    }
