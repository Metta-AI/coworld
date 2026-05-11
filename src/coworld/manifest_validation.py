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


def validate_coworld_manifest_game_configs(manifest: CoworldManifest) -> int:
    token_count = infer_fixed_token_count(manifest.game.config_schema)
    if len(manifest.certification.players) != token_count:
        raise ValueError("certification.players must match game.config_schema token count")

    tokens = [f"token-{slot}" for slot in range(token_count)]
    for index, variant in enumerate(manifest.variants):
        validate_json_schema(
            game_config_with_tokens(variant.game_config, tokens),
            manifest.game.config_schema,
        )
        if variant.parent_id is not None and variant.parent_id not in {v.id for v in manifest.variants}:
            raise ValueError(f"unknown variants[{index}].parent_id: {variant.parent_id!r}")

    validate_json_schema(
        game_config_with_tokens(manifest.certification.game_config, tokens),
        manifest.game.config_schema,
    )
    return token_count
