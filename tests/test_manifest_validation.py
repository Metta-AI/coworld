import pytest
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError

from coworld.manifest_validation import (
    game_config_with_named_players,
    game_config_with_overwritten_named_players,
    infer_token_count_for_game_config,
    validate_authored_game_config,
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
    schema: dict[str, object] = {"type": "object"}

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


def test_game_config_with_overwritten_named_players_resizes_existing_players() -> None:
    schema = FIXED_NAMED_PLAYERS_SCHEMA | {
        "properties": FIXED_NAMED_PLAYERS_SCHEMA["properties"]
        | {
            "tokens": FIXED_NAMED_PLAYERS_SCHEMA["properties"]["tokens"] | {"maxItems": 3},
            "players": FIXED_NAMED_PLAYERS_SCHEMA["properties"]["players"]
            | {
                "maxItems": 3,
                "items": FIXED_NAMED_PLAYERS_SCHEMA["properties"]["players"]["items"]
                | {"properties": {"name": {"type": "string"}, "role": {"type": "string"}}},
            },
        }
    }

    config = game_config_with_overwritten_named_players(
        {"players": [{"name": "Old A", "role": "red"}, {"name": "Old B", "role": "blue"}]},
        ["alpha", "beta", "alpha"],
        schema,
    )

    assert config == {
        "players": [
            {"name": "alpha", "role": "red"},
            {"name": "beta", "role": "blue"},
            {"name": "alpha (2)", "role": "red"},
        ]
    }


def test_validate_manifest_requires_tokens_schema() -> None:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["players"],
        "properties": {"players": FIXED_NAMED_PLAYERS_SCHEMA["properties"]["players"]},
    }

    with pytest.raises(ValueError, match="game.config_schema must require tokens"):
        validate_coworld_manifest_game_configs(_manifest(schema))


def test_validate_manifest_allows_bounded_tokens_and_variant_specific_player_counts() -> None:
    schema = FIXED_NAMED_PLAYERS_SCHEMA | {
        "properties": FIXED_NAMED_PLAYERS_SCHEMA["properties"]
        | {
            "tokens": {"type": "array", "minItems": 2, "maxItems": 4, "items": {"type": "string"}},
            "players": FIXED_NAMED_PLAYERS_SCHEMA["properties"]["players"] | {"maxItems": 4},
        }
    }
    manifest = CoworldManifest.model_construct(
        game=CoworldGameManifest.model_construct(config_schema=schema),
        variants=[
            CoworldVariant.model_construct(
                id="two-player",
                game_config={"players": [{"name": "A"}, {"name": "B"}]},
            ),
            CoworldVariant.model_construct(
                id="four-player", game_config={"players": [{"name": "A"}, {"name": "B"}, {"name": "C"}, {"name": "D"}]}
            ),
        ],
        certification=CoworldCertificationFixture.model_construct(
            game_config={"players": [{"name": "A"}, {"name": "B"}]},
            players=[object(), object()],
        ),
    )

    validate_coworld_manifest_game_configs(manifest)
    assert infer_token_count_for_game_config(schema, manifest.variants[1].game_config) == 4


def test_infer_token_count_uses_game_config_players_when_schema_lacks_players_property() -> None:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["tokens"],
        "properties": {
            "tokens": {"type": "array", "minItems": 0, "maxItems": 9, "items": {"type": "string"}},
        },
    }
    game_config = {
        "players": [
            {"name": "Cybertank 1"},
            {"name": "Cybertank 2"},
            {"name": "Cybertank 3"},
            {"name": "Cybertank 4"},
        ]
    }

    assert infer_token_count_for_game_config(schema, game_config) == 4


def test_infer_token_count_rejects_players_roster_outside_token_bounds() -> None:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["tokens"],
        "properties": {
            "tokens": {"type": "array", "minItems": 0, "maxItems": 3, "items": {"type": "string"}},
        },
    }
    game_config = {
        "players": [
            {"name": "Cybertank 1"},
            {"name": "Cybertank 2"},
            {"name": "Cybertank 3"},
            {"name": "Cybertank 4"},
        ]
    }

    with pytest.raises(
        ValueError,
        match="game_config.players length must fit game.config_schema.properties.tokens bounds",
    ):
        infer_token_count_for_game_config(schema, game_config)


def test_infer_token_count_returns_none_for_variable_tokens_without_players() -> None:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["tokens"],
        "properties": {
            "tokens": {"type": "array", "minItems": 0, "maxItems": 9, "items": {"type": "string"}},
        },
    }
    game_config = {"seed": 1, "maxGames": 1, "maxTicks": 1200}

    assert infer_token_count_for_game_config(schema, game_config) is None


def test_validate_manifest_requires_token_bounds() -> None:
    schema = FIXED_NAMED_PLAYERS_SCHEMA | {
        "properties": FIXED_NAMED_PLAYERS_SCHEMA["properties"]
        | {
            "tokens": {"type": "array", "items": {"type": "string"}},
        }
    }

    with pytest.raises(ValueError, match="tokens must declare minItems and maxItems"):
        validate_coworld_manifest_game_configs(_manifest(schema))


def test_validate_manifest_rejects_token_free_game_schema() -> None:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["map"],
        "properties": {"map": {"type": "string"}},
    }
    manifest = _manifest(schema)
    manifest.variants[0].game_config = {"map": "arena"}
    manifest.certification.game_config = {"map": "arena"}

    with pytest.raises(ValueError, match="game.config_schema must require tokens"):
        validate_coworld_manifest_game_configs(manifest)


def test_validate_authored_game_config_uses_supplied_token_count() -> None:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["tokens"],
        "properties": {
            "tokens": {"type": "array", "minItems": 2, "maxItems": 4, "items": {"type": "string"}},
        },
    }

    validate_authored_game_config({}, schema, token_count=3)

    with pytest.raises(JsonSchemaValidationError):
        validate_authored_game_config({}, schema, token_count=5)


def test_validate_manifest_requires_certification_players_to_match_authored_players() -> None:
    manifest = _manifest(FIXED_NAMED_PLAYERS_SCHEMA)
    manifest.certification = CoworldCertificationFixture.model_construct(
        game_config={"players": [{"name": "A"}, {"name": "B"}]},
        players=[object()],
    )

    with pytest.raises(ValueError, match="certification.players must match certification game_config.players length"):
        validate_coworld_manifest_game_configs(manifest)


def test_validate_manifest_rejects_duplicate_variant_ids() -> None:
    manifest = _manifest(FIXED_NAMED_PLAYERS_SCHEMA)
    manifest.variants.append(
        CoworldVariant.model_construct(
            id="two-player",
            game_config={"players": [{"name": "A"}, {"name": "B"}]},
        )
    )

    with pytest.raises(ValueError, match="duplicate variant id"):
        validate_coworld_manifest_game_configs(manifest)


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
        variants=[
            CoworldVariant.model_construct(
                id="two-player",
                game_config={"players": [{"name": "A"}, {"name": "B"}]},
            )
        ],
        certification=CoworldCertificationFixture.model_construct(
            game_config={"players": [{"name": "A"}, {"name": "B"}]},
            players=[object(), object()],
        ),
    )
