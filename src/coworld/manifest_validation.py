from __future__ import annotations

import copy
from typing import Any, cast

from coworld.schema_validation import JsonObject, JsonSchema, validate_json_schema
from coworld.types import CoworldManifest


def infer_fixed_token_count(config_schema: JsonSchema) -> int:
    required = config_schema.get("required")
    if not isinstance(required, list) or "tokens" not in required:
        raise ValueError("game.config_schema must require tokens")

    properties = config_schema.get("properties")
    if not isinstance(properties, dict):
        raise ValueError("game.config_schema must define properties")

    tokens = properties.get("tokens")
    if not isinstance(tokens, dict):
        raise ValueError("game.config_schema.properties.tokens must be an object")
    if tokens.get("type") != "array":
        raise ValueError("game.config_schema.properties.tokens.type must be array")

    items = tokens.get("items")
    if not isinstance(items, dict) or items.get("type") != "string":
        raise ValueError("game.config_schema.properties.tokens.items.type must be string")

    min_items = tokens.get("minItems")
    max_items = tokens.get("maxItems")
    if not isinstance(min_items, int) or not isinstance(max_items, int) or min_items != max_items:
        raise ValueError("game.config_schema.properties.tokens must declare equal minItems and maxItems")
    return min_items


def game_config_with_tokens(game_config: dict[str, Any], tokens: list[str]) -> JsonObject:
    if "tokens" in game_config:
        raise ValueError("game_config must not include runner-managed tokens")
    playable_config = copy.deepcopy(game_config)
    playable_config["tokens"] = tokens
    return cast(JsonObject, playable_config)


def game_config_with_named_players(
    game_config: dict[str, Any],
    player_names: list[str],
    config_schema: JsonSchema,
) -> JsonObject:
    if "player_names" in game_config:
        raise ValueError("game_config.player_names is not supported; use game_config.players[].name")

    named_config = copy.deepcopy(game_config)
    properties = config_schema.get("properties", {})
    if isinstance(properties, dict) and _declares_named_players(properties.get("players")):
        names: list[str] = []
        used_names: set[str] = set()
        for player_name in player_names:
            name = player_name
            suffix = 2
            while name in used_names:
                name = f"{player_name} ({suffix})"
                suffix += 1
            used_names.add(name)
            names.append(name)
        players = named_config.get("players", [{} for _ in names])
        player_configs = _player_config_objects(players, "game_config.players")
        if len(player_configs) != len(names):
            raise ValueError("game_config.players must match resolved player count")
        named_config["players"] = [
            {**player_config, "name": player_name}
            for player_config, player_name in zip(player_configs, names, strict=True)
        ]
        return cast(JsonObject, named_config)

    return cast(JsonObject, named_config)


def _declares_named_players(value: Any) -> bool:
    if not isinstance(value, dict) or value.get("type") != "array":
        return False
    items = value.get("items")
    if not isinstance(items, dict) or items.get("type") != "object":
        return False
    properties = items.get("properties")
    if not isinstance(properties, dict):
        return False
    name = properties.get("name")
    return isinstance(name, dict) and name.get("type") == "string"


def _player_config_objects(value: Any, field_name: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"{field_name} must be a list of objects")
    return cast(list[dict[str, Any]], value)


def validate_coworld_manifest_game_configs(manifest: CoworldManifest) -> int:
    _reject_legacy_name_config_schema(manifest.game.config_schema)
    token_count = infer_fixed_token_count(manifest.game.config_schema)
    player_count = _infer_fixed_named_player_count(manifest.game.config_schema)
    if player_count is not None and player_count != token_count:
        raise ValueError("game.config_schema.properties.players must declare the same fixed length as tokens")
    if len(manifest.certification.players) != token_count:
        raise ValueError("certification.players must match game.config_schema token count")

    tokens = [f"token-{slot}" for slot in range(token_count)]
    for variant in manifest.variants:
        validate_json_schema(
            game_config_with_tokens(variant.game_config, tokens),
            manifest.game.config_schema,
        )

    validate_json_schema(
        game_config_with_tokens(manifest.certification.game_config, tokens),
        manifest.game.config_schema,
    )
    return token_count


def _reject_legacy_name_config_schema(config_schema: JsonSchema) -> None:
    properties = config_schema.get("properties")
    if not isinstance(properties, dict):
        return
    if "player_names" in properties:
        raise ValueError("game.config_schema.properties.player_names is not supported; use players[].name")
    slots = properties.get("slots")
    if not isinstance(slots, dict):
        return
    items = slots.get("items")
    if not isinstance(items, dict):
        return
    slot_properties = items.get("properties")
    if isinstance(slot_properties, dict) and "name" in slot_properties:
        raise ValueError(
            "game.config_schema.properties.slots.items.properties.name is not supported; use players[].name"
        )


def _infer_fixed_named_player_count(config_schema: JsonSchema) -> int | None:
    properties = config_schema.get("properties")
    if not isinstance(properties, dict):
        return None
    players = properties.get("players")
    if not _declares_named_players(players):
        return None
    required = config_schema.get("required")
    if not isinstance(required, list) or "players" not in required:
        raise ValueError("game.config_schema must require players when declaring players[].name")
    min_items = players.get("minItems")
    max_items = players.get("maxItems")
    if not isinstance(min_items, int) or not isinstance(max_items, int) or min_items != max_items:
        raise ValueError("game.config_schema.properties.players must declare equal minItems and maxItems")
    items = cast(dict[str, Any], players["items"])
    item_required = items.get("required")
    if not isinstance(item_required, list) or "name" not in item_required:
        raise ValueError("game.config_schema.properties.players.items must require name")
    return min_items
