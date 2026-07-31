from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TypeAlias, cast

from jsonschema import Draft202012Validator, FormatChecker, ValidationError

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


def json_schema_validation_errors(instance: object, schema: JsonSchema) -> list[ValidationError]:
    Draft202012Validator.check_schema(schema)
    return sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(cast(Any, instance)),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
