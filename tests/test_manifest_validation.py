import pytest

from coworld.manifest_validation import game_config_with_player_names, player_names_from_game_config


def test_game_config_with_player_names_updates_players_array() -> None:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "tokens": {"type": "array"},
            "players": {"type": "array", "items": {"type": "object"}},
        },
    }

    config = game_config_with_player_names(
        {"players": [{"team": 0}, {"team": 1}]},
        ["alpha:v1", "beta:v2"],
        schema,
    )

    assert config == {"players": [{"team": 0, "name": "alpha:v1"}, {"team": 1, "name": "beta:v2"}]}
    assert player_names_from_game_config(config) == ["alpha:v1", "beta:v2"]


def test_game_config_with_player_names_creates_slots_array() -> None:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "tokens": {"type": "array"},
            "slots": {"type": "array", "items": {"type": "object"}},
        },
    }

    config = game_config_with_player_names(
        {"slots": [{"role": "crew"}]},
        ["alpha:v1", "beta:v2"],
        schema,
    )

    assert config == {"slots": [{"role": "crew", "name": "alpha:v1"}, {"name": "beta:v2"}]}
    assert player_names_from_game_config(config) == ["alpha:v1", "beta:v2"]


def test_game_config_with_player_names_disambiguates_duplicate_slots() -> None:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "tokens": {"type": "array"},
            "slots": {"type": "array", "items": {"type": "object"}},
        },
    }

    config = game_config_with_player_names(
        {"slots": [{}, {}, {}]},
        ["daveey", "daveey", "daveey (2)"],
        schema,
    )

    assert config == {"slots": [{"name": "daveey"}, {"name": "daveey (2)"}, {"name": "daveey (2) (2)"}]}
    assert player_names_from_game_config(config) == ["daveey", "daveey (2)", "daveey (2) (2)"]


def test_game_config_with_player_names_leaves_optional_slots_absent() -> None:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "tokens": {"type": "array"},
            "slots": {"type": "array", "items": {"type": "object"}},
        },
    }

    config = game_config_with_player_names({}, ["daveey", "daveey"], schema)

    assert config == {}
    assert player_names_from_game_config(config) is None


def test_game_config_with_player_names_uses_player_names_field() -> None:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "tokens": {"type": "array"},
            "player_names": {"type": "array", "items": {"type": "string"}},
        },
    }

    config = game_config_with_player_names({}, ["alpha:v1", "beta:v2"], schema)

    assert config == {"player_names": ["alpha:v1", "beta:v2"]}
    assert player_names_from_game_config(config) == ["alpha:v1", "beta:v2"]


def test_game_config_with_player_names_leaves_unsupported_schema_unchanged() -> None:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "tokens": {"type": "array"},
            "width": {"type": "integer"},
            "height": {"type": "integer"},
        },
    }

    config = game_config_with_player_names({"width": 12, "height": 8}, ["alpha:v1", "beta:v2"], schema)

    assert config == {"width": 12, "height": 8}
    assert player_names_from_game_config(config) is None


def test_game_config_with_player_names_rejects_existing_player_names() -> None:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "tokens": {"type": "array"},
            "player_names": {"type": "array", "items": {"type": "string"}},
        },
    }

    with pytest.raises(ValueError, match="game_config must not include commissioner-managed player_names"):
        game_config_with_player_names({"player_names": ["stale"]}, ["alpha:v1"], schema)


def test_player_names_from_game_config_ignores_unnamed_slots() -> None:
    assert player_names_from_game_config({"players": [{"team": 0}, {"team": 1}]}) is None
    assert player_names_from_game_config({"slots": [{"role": "crew"}]}) is None


def test_player_names_from_game_config_rejects_partial_slot_names() -> None:
    with pytest.raises(ValueError, match="game_config.players entries must all define name"):
        player_names_from_game_config({"players": [{"name": "alpha:v1"}, {"team": 1}]})
