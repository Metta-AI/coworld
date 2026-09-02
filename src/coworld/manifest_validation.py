from __future__ import annotations

import copy
from typing import Any, cast

from coworld.schema_validation import JsonObject, JsonSchema, json_schema_validation_errors
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


def infer_token_count_for_game_config(
    config_schema: JsonSchema,
    game_config: dict[str, Any],
) -> int | None:
    """Infer a concrete seat count from the manifest or caller roster.

    Returns the roster length from `game_config.players` when present, then
    `game_config.num_agents` when that field is a positive int, then the
    legacy fixed token count when the manifest pins `tokens` to a single
    length. Returns `None` when the manifest is variable-length and the
    caller must supply the seated roster size.
    """
    min_items, max_items = token_count_bounds(config_schema)
    players = game_config.get("players")
    if isinstance(players, list):
        player_count = len(players)
        if player_count < min_items or player_count > max_items:
            raise ValueError("game_config.players length must fit game.config_schema.properties.tokens bounds")
        return player_count

    num_agents = game_config.get("num_agents")
    if isinstance(num_agents, int) and num_agents > 0:
        if num_agents < min_items or num_agents > max_items:
            raise ValueError("game_config.num_agents must fit game.config_schema.properties.tokens bounds")
        return num_agents

    if min_items == max_items:
        return min_items

    return None


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

    # A config/schema mismatch is a caller error, not an internal failure: raise
    # the same ValueError contract as every other check in this module so API
    # layers map it to a 4xx instead of a retryable 500. Delegating to the
    # string-returning sibling keeps this module to a single formatter.
    detail = authored_game_config_validation_error(game_config, config_schema, token_count=token_count)
    if detail is None:
        return
    if detail.startswith("at "):
        raise ValueError(f"game_config is invalid {detail}")
    raise ValueError(detail)


def authored_game_config_validation_error(
    game_config: dict[str, Any],
    config_schema: JsonSchema,
    *,
    token_count: int | None = None,
) -> str | None:
    """Return an actionable client error while preserving malformed-schema failures."""

    _token_array_schema(config_schema)
    if "tokens" in game_config:
        return "game_config must not include runner-managed tokens"
    if token_count is None:
        players = game_config.get("players")
        if isinstance(players, list):
            min_items, max_items = token_count_bounds(config_schema)
            if not min_items <= len(players) <= max_items:
                return "game_config.players length must fit game.config_schema.properties.tokens bounds"
            token_count = len(players)
        else:
            num_agents = game_config.get("num_agents")
            if isinstance(num_agents, int) and num_agents > 0:
                min_items, max_items = token_count_bounds(config_schema)
                if not min_items <= num_agents <= max_items:
                    return "game_config.num_agents must fit game.config_schema.properties.tokens bounds"
                token_count = num_agents
            else:
                token_count = _placeholder_token_count(config_schema, game_config)
    playable_config = copy.deepcopy(game_config)
    playable_config["tokens"] = [f"token-{slot}" for slot in range(token_count)]
    errors = json_schema_validation_errors(playable_config, config_schema)
    if not errors:
        return None
    error = errors[0]
    location = ".".join(str(part) for part in error.absolute_path) or "config"
    return f"at {location}: {error.message}"


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


def game_config_with_input_player_controls(
    game_config: dict[str, Any],
    player_positions: list[int],
    config_schema: JsonSchema,
) -> JsonObject:
    """Use the standard external-player transport for configured lobby seats."""

    input_config = copy.deepcopy(game_config)
    properties = config_schema.get("properties")
    if not isinstance(properties, dict):
        return cast(JsonObject, input_config)
    slots_schema = properties.get("slots")
    if not isinstance(slots_schema, dict) or slots_schema.get("type") != "array":
        return cast(JsonObject, input_config)
    items_schema = slots_schema.get("items")
    if not isinstance(items_schema, dict) or items_schema.get("type") != "object":
        return cast(JsonObject, input_config)
    slot_properties = items_schema.get("properties")
    if not isinstance(slot_properties, dict):
        return cast(JsonObject, input_config)
    control_schema = slot_properties.get("control")
    if not isinstance(control_schema, dict) or control_schema.get("type") != "string":
        return cast(JsonObject, input_config)
    control_values = control_schema.get("enum")
    if not isinstance(control_values, list) or "input" not in control_values or "play" not in control_values:
        return cast(JsonObject, input_config)

    if not player_positions:
        return cast(JsonObject, input_config)
    slots = input_config.get("slots", [])
    slot_configs = _player_config_objects(slots, "game_config.slots")
    slot_configs.extend({} for _ in range(max(player_positions) + 1 - len(slot_configs)))
    for position in player_positions:
        slot_configs[position] = {**slot_configs[position], "control": "input"}
    input_config["slots"] = slot_configs
    return cast(JsonObject, input_config)


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
    token_count_bounds(manifest.game.config_schema)
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
    inferred = infer_token_count_for_game_config(config_schema, game_config)
    if inferred is not None:
        return inferred
    min_items, _max_items = token_count_bounds(config_schema)
    return min_items


def token_count_bounds(config_schema: JsonSchema) -> tuple[int, int]:
    tokens = _token_array_schema(config_schema)
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
