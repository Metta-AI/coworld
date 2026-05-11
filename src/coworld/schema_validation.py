from __future__ import annotations

import json
from pathlib import Path
from typing import TypeAlias, cast

from jsonschema import Draft202012Validator, FormatChecker

JsonObject: TypeAlias = dict[str, object]
JsonSchema: TypeAlias = dict[str, object]


def load_json_object(path: Path) -> JsonObject:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise TypeError(f"Expected JSON object in {path}")
    return cast(JsonObject, value)


def validate_json_schema(instance: object, schema: JsonSchema) -> None:
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(instance)
