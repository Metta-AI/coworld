"""CI enforcement for Coworld manifest schema declarations and fixtures."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from coworld.manifest.registry import (
    COWORLD_MANIFEST_V0,
    COWORLD_MANIFEST_V1,
    ManifestVersion,
    manifest_schema_hash,
    validate_upload_manifest,
)
from coworld.manifest.v0.model import V0Manifest
from coworld.manifest.v1.model import V1Manifest
from coworld.types import coworld_manifest_schema

REPO_ROOT = Path(__file__).resolve().parents[5]
BASE_SCHEMA_PATH = "packages/coworld/src/coworld/coworld_manifest_schema.json"
DECLARATION_PATHS: dict[ManifestVersion, str] = {
    COWORLD_MANIFEST_V0: "packages/coworld/src/coworld/manifest/v0/declarations.yaml",
    COWORLD_MANIFEST_V1: "packages/coworld/src/coworld/manifest/v1/declarations.yaml",
}
SCHEMA_PATHS: dict[ManifestVersion, str] = {
    COWORLD_MANIFEST_V0: "packages/coworld/src/coworld/manifest/v0/schema.json",
    COWORLD_MANIFEST_V1: "packages/coworld/src/coworld/manifest/v1/schema.json",
}


class SchemaDeclaration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    kind: Literal["initial", "toolchain", "annotation", "compatible"]
    summary: str = Field(min_length=1)
    fixture: str = Field(min_length=1)


# min_length=1: every major ships with its initial declaration, so an empty log is
# always an authoring error — reject it with a validation message, not an IndexError
# at declarations[-1].
_DECLARATIONS = TypeAdapter(Annotated[list[SchemaDeclaration], Field(min_length=1)])


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def _load_declarations(text: str) -> list[SchemaDeclaration]:
    return _DECLARATIONS.validate_python(yaml.safe_load(text))


def _obvious_narrowings(before: dict[str, Any], after: dict[str, Any], path: str = "$") -> list[str]:
    """Find structural changes that unambiguously reject previously valid JSON."""
    findings: list[str] = []
    old_required = set(before.get("required", []))
    new_required = set(after.get("required", []))
    for field in sorted(new_required - old_required):
        findings.append(f"{path}: newly required field {field!r}")

    old_properties = before.get("properties", {})
    new_properties = after.get("properties", {})
    if before.get("additionalProperties") is False and after.get("additionalProperties") is False:
        for field in sorted(set(old_properties) - set(new_properties)):
            findings.append(f"{path}: removed accepted field {field!r}")
    for field in sorted(set(old_properties) & set(new_properties)):
        findings.extend(_obvious_narrowings(old_properties[field], new_properties[field], f"{path}.{field}"))
    old_defs = before.get("$defs", {})
    new_defs = after.get("$defs", {})
    for name in sorted(set(old_defs) & set(new_defs)):
        findings.extend(_obvious_narrowings(old_defs[name], new_defs[name], f"{path}.$defs.{name}"))

    old_enum = set(before.get("enum", []))
    new_enum = set(after.get("enum", []))
    if old_enum and new_enum and not old_enum.issubset(new_enum):
        findings.append(f"{path}: removed enum values {sorted(old_enum - new_enum)!r}")

    lower_bounds = ("minimum", "exclusiveMinimum", "minLength", "minItems", "minProperties")
    upper_bounds = ("maximum", "exclusiveMaximum", "maxLength", "maxItems", "maxProperties")
    for keyword in lower_bounds:
        if keyword in before and keyword in after and after[keyword] > before[keyword]:
            findings.append(f"{path}: raised {keyword} from {before[keyword]} to {after[keyword]}")
    for keyword in upper_bounds:
        if keyword in before and keyword in after and after[keyword] < before[keyword]:
            findings.append(f"{path}: lowered {keyword} from {before[keyword]} to {after[keyword]}")
    return findings


def check_manifest_schema(against: str) -> list[str]:
    """Return actionable CI failures; an empty list means the schema contract is coherent."""
    ref = _git("rev-parse", "--verify", f"{against}^{{commit}}")
    if ref.returncode:
        return [
            f"Cannot compare Coworld schemas because {against!r} is missing. "
            "Fetch the base ref first (for GitHub Actions, use checkout fetch-depth: 0)."
        ]

    failures: list[str] = []
    versions: tuple[tuple[ManifestVersion, type[BaseModel]], ...] = (
        (COWORLD_MANIFEST_V0, V0Manifest),
        (COWORLD_MANIFEST_V1, V1Manifest),
    )
    for version, model in versions:
        current_schema = model.model_json_schema(by_alias=True)
        declaration_path = REPO_ROOT / DECLARATION_PATHS[version]
        declarations = _load_declarations(declaration_path.read_text())
        current_hash = manifest_schema_hash(version)
        if declarations[-1].schema_hash != current_hash:
            failures.append(
                f"{DECLARATION_PATHS[version]} must end with the generated {version} schema hash {current_hash}"
            )
        fixture_path = REPO_ROOT / declarations[-1].fixture
        if not fixture_path.is_file():
            failures.append(f"{DECLARATION_PATHS[version]} references missing fixture {fixture_path}")
        else:
            document = json.loads(fixture_path.read_text())
            validated = validate_upload_manifest(document)
            if validated.api_version != version:
                failures.append(f"{fixture_path} validates as {validated.api_version}, not {version}")

        base_schema = _git("show", f"{against}:{SCHEMA_PATHS[version]}")
        base_declarations = _git("show", f"{against}:{DECLARATION_PATHS[version]}")
        if base_schema.returncode or base_declarations.returncode:
            continue
        old_schema = json.loads(base_schema.stdout)
        old_declarations = _load_declarations(base_declarations.stdout)
        schema_changed = old_schema != current_schema
        declaration_added = declarations[:-1] == old_declarations
        if schema_changed and not declaration_added:
            failures.append(
                f"{version} changed without exactly one new declaration appended to the existing log "
                "(prior entries must be byte-identical)"
            )
        if not schema_changed and declarations != old_declarations:
            failures.append(f"{version} declarations changed but its generated schema did not")
        if schema_changed and declaration_added:
            old_fixtures = {entry.fixture for entry in old_declarations}
            if declarations[-1].fixture in old_fixtures:
                failures.append(f"{version} schema change must add a new fixture path")
            for narrowing in _obvious_narrowings(old_schema, current_schema):
                failures.append(
                    f"{version} structurally narrows and must be introduced as a new apiVersion: {narrowing}"
                )

    base_schema = _git("show", f"{against}:{BASE_SCHEMA_PATH}")
    if base_schema.returncode:
        failures.append(f"Cannot read {BASE_SCHEMA_PATH} from {against}; verify the base ref and checkout history")
    elif (
        json.loads(base_schema.stdout) != coworld_manifest_schema()
        and _git("show", f"{against}:{SCHEMA_PATHS[COWORLD_MANIFEST_V0]}").returncode
    ):
        failures.append("Do not bootstrap manifest versioning and change the v0 schema in the same change")
    return failures
