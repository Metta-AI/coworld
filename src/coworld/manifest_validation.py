from __future__ import annotations

import copy
from typing import Any, cast

from coworld.schema_validation import JsonObject, JsonSchema, validate_json_schema
from coworld.types import CoworldManifest


def _token_array_schema(config_schema: JsonSchema) -> dict[str, Any]:
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
    return tokens


def infer_token_count_for_game_config(config_schema: JsonSchema, game_config: dict[str, Any]) -> int:
    tokens = _token_array_schema(config_schema)
    properties = config_schema.get("properties")
    players_schema = properties.get("players") if isinstance(properties, dict) else None
    if isinstance(players_schema, dict) and players_schema.get("type") == "array":
        players = game_config.get("players")
        if isinstance(players, list):
            player_count = len(players)
            min_items, max_items = _token_bounds(tokens)
            if player_count < min_items:
                raise ValueError("game_config.players length must fit game.config_schema.properties.tokens bounds")
            if player_count > max_items:
                raise ValueError("game_config.players length must fit game.config_schema.properties.tokens bounds")
            return player_count

    min_items, max_items = _token_bounds(tokens)
    if min_items == max_items:
        return min_items

    raise ValueError("player_count must be provided when tokens do not declare a legacy fixed length")


def game_config_with_tokens(game_config: dict[str, Any], tokens: list[str]) -> JsonObject:
    if "tokens" in game_config:
        raise ValueError("game_config must not include runner-managed tokens")
    playable_config = copy.deepcopy(game_config)
    playable_config["tokens"] = tokens
    return cast(JsonObject, playable_config)


def validate_authored_game_config(
    game_config: dict[str, Any],
    config_schema: JsonSchema,
    *,
    token_count: int | None = None,
) -> None:
    """Validate manifest-authored config without requiring runner-injected tokens.

    Coworld manifests declare the runner-injected auth tokens in the runtime
    config schema, but authored configs omit them. The caller supplies the token
    count when a concrete roster is known.
    """

    _token_array_schema(config_schema)
    if token_count is None:
        token_count = _placeholder_token_count(config_schema, game_config)
    validate_json_schema(
        game_config_with_tokens(game_config, [f"token-{slot}" for slot in range(token_count)]),
        config_schema,
    )


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


def game_config_with_overwritten_named_players(
    game_config: dict[str, Any],
    player_names: list[str],
    config_schema: JsonSchema,
) -> JsonObject:
    if "player_names" in game_config:
        raise ValueError("game_config.player_names is not supported; use game_config.players[].name")

    named_config = copy.deepcopy(game_config)
    properties = config_schema.get("properties", {})
    if isinstance(properties, dict) and _declares_named_players(properties.get("players")):
        names = _unique_player_names(player_names)
        existing_players = named_config.get("players")
        if existing_players is None:
            player_configs = [{} for _ in names]
        else:
            existing_player_configs = _player_config_objects(existing_players, "game_config.players")
            if existing_player_configs:
                player_configs = [
                    copy.deepcopy(existing_player_configs[index % len(existing_player_configs)])
                    for index in range(len(names))
                ]
            else:
                player_configs = [{} for _ in names]
        named_config["players"] = [
            {**player_config, "name": player_name}
            for player_config, player_name in zip(player_configs, names, strict=True)
        ]
        return cast(JsonObject, named_config)

    return cast(JsonObject, named_config)


def validate_game_config_players_match_count(game_config: dict[str, Any], player_count: int) -> None:
    players = game_config.get("players")
    if isinstance(players, list) and len(players) != player_count:
        raise ValueError("game_config.players must match resolved player count")


def _unique_player_names(player_names: list[str]) -> list[str]:
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
    return names


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


def validate_coworld_manifest_game_configs(manifest: CoworldManifest) -> None:
    _reject_legacy_name_config_schema(manifest.game.config_schema)
    _token_bounds(_token_array_schema(manifest.game.config_schema))
    variant_ids: set[str] = set()
    for variant in manifest.variants:
        if variant.id in variant_ids:
            raise ValueError(f"duplicate variant id: {variant.id!r}")
        variant_ids.add(variant.id)
        validate_authored_game_config(variant.game_config, manifest.game.config_schema)

    certification_players_config = manifest.certification.game_config.get("players")
    if isinstance(certification_players_config, list) and len(certification_players_config) != len(
        manifest.certification.players
    ):
        raise ValueError("certification.players must match certification game_config.players length")
    validate_authored_game_config(
        manifest.certification.game_config,
        manifest.game.config_schema,
        token_count=len(manifest.certification.players),
    )


def _placeholder_token_count(config_schema: JsonSchema, game_config: dict[str, Any]) -> int:
    players = game_config.get("players")
    if isinstance(players, list):
        return len(players)

    tokens = _token_array_schema(config_schema)
    min_items, _max_items = _token_bounds(tokens)
    return min_items


def _token_bounds(tokens: dict[str, Any]) -> tuple[int, int]:
    min_items = tokens.get("minItems")
    max_items = tokens.get("maxItems")
    if not isinstance(min_items, int) or not isinstance(max_items, int):
        raise ValueError("game.config_schema.properties.tokens must declare minItems and maxItems")
    if min_items > max_items:
        raise ValueError("game.config_schema.properties.tokens minItems must not exceed maxItems")
    return min_items, max_items


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
