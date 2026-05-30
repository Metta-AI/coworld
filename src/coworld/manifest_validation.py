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


def game_config_with_player_names(
    game_config: dict[str, Any],
    player_names: list[str],
    config_schema: JsonSchema,
) -> JsonObject:
    if "player_names" in game_config:
        raise ValueError("game_config must not include commissioner-managed player_names")

    named_config = copy.deepcopy(game_config)
    if "players" in named_config:
        return _game_config_with_slot_names(named_config, player_names, "players")
    if "slots" in named_config:
        return _game_config_with_slot_names(named_config, player_names, "slots")
    if (
        _schema_has_property(config_schema, "player_names")
        or config_schema.get("additionalProperties", True) is not False
    ):
        named_config["player_names"] = list(player_names)
        return cast(JsonObject, named_config)

    return cast(JsonObject, named_config)


def player_names_from_game_config(game_config: dict[str, Any]) -> list[str] | None:
    if "player_names" in game_config:
        return _string_list(game_config["player_names"], "game_config.player_names")
    if "players" in game_config:
        return _slot_names(game_config["players"], "game_config.players")
    if "slots" in game_config:
        return _slot_names(game_config["slots"], "game_config.slots")
    return None


def _schema_has_property(config_schema: JsonSchema, field_name: str) -> bool:
    properties = config_schema.get("properties", {})
    return isinstance(properties, dict) and field_name in properties


def _game_config_with_slot_names(
    game_config: dict[str, Any],
    player_names: list[str],
    slot_field: str,
) -> JsonObject:
    raw_slots = game_config[slot_field] if slot_field in game_config else []
    if not isinstance(raw_slots, list):
        raise ValueError(f"game_config.{slot_field} must be a list")
    if len(raw_slots) > len(player_names):
        raise ValueError(f"game_config.{slot_field} must not have more entries than player_names")

    slots: list[dict[str, Any]] = []
    used_names: set[str] = set()
    for slot, player_name in enumerate(player_names):
        slot_config = copy.deepcopy(raw_slots[slot]) if slot < len(raw_slots) else {}
        if not isinstance(slot_config, dict):
            raise ValueError(f"game_config.{slot_field}[{slot}] must be an object")
        slot_name = player_name
        suffix = 2
        while slot_name in used_names:
            slot_name = f"{player_name} ({suffix})"
            suffix += 1
        used_names.add(slot_name)
        slot_config["name"] = slot_name
        slots.append(slot_config)

    game_config[slot_field] = slots
    return cast(JsonObject, game_config)


def _string_list(value: Any, field_name: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{field_name} must be a list of strings")
    return list(value)


def _slot_names(value: Any, field_name: str) -> list[str] | None:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list")
    names: list[str | None] = []
    has_names = False
    for slot, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError(f"{field_name}[{slot}] must be an object")
        if "name" not in item:
            names.append(None)
            continue
        if not isinstance(item["name"], str):
            raise ValueError(f"{field_name}[{slot}].name must be a string")
        has_names = True
        names.append(item["name"])
    if not has_names:
        return None
    if any(name is None for name in names):
        raise ValueError(f"{field_name} entries must all define name when any entry defines one")
    return cast(list[str], names)


def validate_coworld_manifest_game_configs(manifest: CoworldManifest) -> int:
    token_count = infer_fixed_token_count(manifest.game.config_schema)
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
