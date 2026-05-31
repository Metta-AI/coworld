import pytest

from coworld.manifest_validation import (
    game_config_with_named_players,
    validate_coworld_manifest_game_configs,
)
from coworld.types import CoworldCertificationFixture, CoworldGameManifest, CoworldManifest, CoworldVariant

NAMED_PLAYERS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "tokens": {"type": "array"},
        "players": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
            },
        },
    },
}

FIXED_NAMED_PLAYERS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["tokens", "players"],
    "properties": {
        "tokens": {"type": "array", "minItems": 2, "maxItems": 2, "items": {"type": "string"}},
        "players": {
            "type": "array",
            "minItems": 2,
            "maxItems": 2,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name"],
                "properties": {"name": {"type": "string"}},
            },
        },
    },
}


def test_game_config_with_named_players_uses_declared_players_name_field() -> None:
    config = game_config_with_named_players({"width": 12}, ["alpha:v1", "beta:v2"], NAMED_PLAYERS_SCHEMA)

    assert config == {"width": 12, "players": [{"name": "alpha:v1"}, {"name": "beta:v2"}]}


def test_game_config_with_named_players_disambiguates_duplicate_player_names() -> None:
    config = game_config_with_named_players({}, ["daveey", "daveey", "daveey (2)"], NAMED_PLAYERS_SCHEMA)

    assert config == {"players": [{"name": "daveey"}, {"name": "daveey (2)"}, {"name": "daveey (2) (2)"}]}


def test_game_config_with_named_players_leaves_open_schema_unchanged() -> None:
    schema = {"type": "object"}

    config = game_config_with_named_players({"width": 12}, ["alpha:v1", "beta:v2"], schema)

    assert config == {"width": 12}


def test_game_config_with_named_players_leaves_noncanonical_name_shapes_unchanged() -> None:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "tokens": {"type": "array"},
            "slots": {"type": "array", "items": {"type": "object"}},
        },
    }
    config = {"slots": [{"role": "crew"}]}

    assert game_config_with_named_players(config, ["alpha:v1"], schema) == config


def test_game_config_with_named_players_rejects_existing_player_names() -> None:
    with pytest.raises(ValueError, match=r"game_config.player_names is not supported"):
        game_config_with_named_players({"player_names": ["stale"]}, ["alpha:v1"], NAMED_PLAYERS_SCHEMA)


def test_validate_manifest_requires_players_to_match_token_count() -> None:
    schema = FIXED_NAMED_PLAYERS_SCHEMA | {
        "properties": FIXED_NAMED_PLAYERS_SCHEMA["properties"]
        | {
            "players": FIXED_NAMED_PLAYERS_SCHEMA["properties"]["players"] | {"minItems": 3, "maxItems": 3},
        }
    }

    with pytest.raises(ValueError, match="players must declare the same fixed length as tokens"):
        validate_coworld_manifest_game_configs(_manifest(schema))


def test_validate_manifest_rejects_legacy_player_name_schema() -> None:
    schema = FIXED_NAMED_PLAYERS_SCHEMA | {
        "properties": FIXED_NAMED_PLAYERS_SCHEMA["properties"]
        | {"player_names": {"type": "array", "items": {"type": "string"}}}
    }

    with pytest.raises(ValueError, match="properties.player_names is not supported"):
        validate_coworld_manifest_game_configs(_manifest(schema))


def _manifest(config_schema: dict) -> CoworldManifest:
    return CoworldManifest.model_construct(
        game=CoworldGameManifest.model_construct(config_schema=config_schema),
        variants=[CoworldVariant.model_construct(game_config={"players": [{"name": "A"}, {"name": "B"}]})],
        certification=CoworldCertificationFixture.model_construct(
            game_config={"players": [{"name": "A"}, {"name": "B"}]},
            players=[object(), object()],
        ),
    )
