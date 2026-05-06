from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any, TypeAlias, cast

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

JsonObject: TypeAlias = dict[str, object]
JsonSchema: TypeAlias = dict[str, object]

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
COWORLD_SCHEMA_PATH = PACKAGE_ROOT / "coworld_manifest_schema.json"
EPISODE_SCHEMA_PATH = PACKAGE_ROOT / "episode_request_schema.json"
SCHEMA_PATHS = (COWORLD_SCHEMA_PATH, EPISODE_SCHEMA_PATH)


def load_json_object(path: Path) -> JsonObject:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise TypeError(f"Expected JSON object in {path}")
    return cast(JsonObject, value)


def validate_coworld_manifest(instance: object) -> None:
    validate_repo_schema(instance, COWORLD_SCHEMA_PATH)


def validate_episode_request(instance: object) -> None:
    validate_repo_schema(instance, EPISODE_SCHEMA_PATH)


def validate_json_schema(instance: object, schema: JsonSchema) -> None:
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(instance)


def validate_repo_schema(instance: object, schema_path: Path) -> None:
    schemas, registry = _schema_registry()
    Draft202012Validator(
        schemas[schema_path],
        registry=registry,
        format_checker=FormatChecker(),
    ).validate(instance)


@cache
def _schema_registry() -> tuple[dict[Path, JsonSchema], Registry[Any]]:
    schemas = {path: _load_schema(path) for path in SCHEMA_PATHS}
    resources = [(str(schema["$id"]), Resource.from_contents(schema, DRAFT202012)) for schema in schemas.values()]
    return schemas, Registry().with_resources(resources)


def _load_schema(path: Path) -> JsonSchema:
    schema = load_json_object(path)
    schema.setdefault("$id", path.as_uri())
    return schema
