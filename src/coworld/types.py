from __future__ import annotations

from typing import Annotated, Any, Literal, cast, get_args

from packaging.version import Version
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = "https://json-schema.org/draft/2020-12/schema"
HTTP_URL_PATTERN = r"^https?://"
JsonSchema = dict[str, Any]
CoworldRunnableRole = Literal["game", "player", "reporter", "commissioner", "grader", "diagnoser", "optimizer"]
CoworldManifestRole = Literal["player", "reporter", "commissioner", "grader", "diagnoser", "optimizer"]
MANIFEST_ROLE_SECTIONS = cast(tuple[CoworldManifestRole, ...], get_args(CoworldManifestRole))


def _runnable_type_schema(runnable_type: str) -> JsonSchema:
    return {"properties": {"type": {"const": runnable_type}}}


class CoworldRunnableSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: CoworldRunnableRole
    image: str
    run: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    source_url: str | None = None

    def as_runnable_spec(self) -> CoworldRunnableSpec:
        return CoworldRunnableSpec.model_validate(self.model_dump(include=set(CoworldRunnableSpec.model_fields)))


class CoworldManifestRoleSpec(CoworldRunnableSpec):
    type: CoworldManifestRole
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)


class CoworldTextDoc(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["text"]
    value: str = Field(min_length=1)


class CoworldUriDoc(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["uri"]
    value: str = Field(min_length=1, pattern=HTTP_URL_PATTERN)


CoworldDoc = Annotated[CoworldTextDoc | CoworldUriDoc, Field(discriminator="type")]


class CoworldProtocolDocs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    player: CoworldDoc
    global_: CoworldDoc = Field(alias="global")


class CoworldDocPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    content: CoworldDoc


class CoworldDocs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    readme: CoworldDoc | None = None
    pages: list[CoworldDocPage] = Field(default_factory=list)


class CoworldGameManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    description: str = Field(min_length=1)
    owner: str = Field(min_length=1)
    config_schema: JsonSchema
    results_schema: JsonSchema
    runnable: Annotated[CoworldRunnableSpec, Field(json_schema_extra=_runnable_type_schema("game"))]
    protocols: CoworldProtocolDocs
    docs: CoworldDocs | None = None

    @model_validator(mode="after")
    def validate_version(self) -> "CoworldGameManifest":
        Version(self.version)
        if self.runnable.type != "game":
            raise ValueError("game.runnable.type must be 'game'")
        return self


class CoworldVariant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    game_config: dict[str, Any]
    description: str = Field(min_length=1)


class CoworldCertificationPlayer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    player_id: str = Field(min_length=1)


class CoworldCertificationFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    game_config: dict[str, Any]
    players: list[CoworldCertificationPlayer] = Field(min_length=1)


class CoworldManifest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        title="Coworld Manifest",
        json_schema_extra={
            "$schema": SCHEMA_VERSION,
            "description": "Schema for a complete game world in the Softmax universe.",
        },
    )

    schema_: str | None = Field(default=None, alias="$schema")
    game: CoworldGameManifest = Field(description="Game runnable and protocol metadata. Role docs: docs/roles/game.md.")
    player: list[CoworldManifestRoleSpec] = Field(
        min_length=1,
        description="Bundled player runnables. Role docs: docs/roles/player.md.",
    )
    reporter: list[CoworldManifestRoleSpec] = Field(
        min_length=1,
        description="Reporter runnables. Must declare at least one entry; Coworlds without a custom reporter "
        "may reference `ghcr.io/metta-ai/reporters-default:latest`. Role docs: docs/roles/reporter.md.",
    )
    commissioner: list[CoworldManifestRoleSpec] = Field(
        default_factory=list,
        description="Optional commissioner runnables. Role docs: docs/roles/commissioner.md.",
    )
    grader: list[CoworldManifestRoleSpec] = Field(
        default_factory=list,
        description="Optional grader runnables. Role docs: docs/roles/grader.md.",
    )
    diagnoser: list[CoworldManifestRoleSpec] = Field(
        default_factory=list,
        description="Optional diagnoser runnables. Role docs: docs/roles/diagnoser.md.",
    )
    optimizer: list[CoworldManifestRoleSpec] = Field(
        default_factory=list,
        description="Optional optimizer runnables. Role docs: docs/roles/optimizer.md.",
    )
    variants: list[CoworldVariant] = Field(min_length=1)
    certification: CoworldCertificationFixture

    @model_validator(mode="after")
    def validate_role_types(self) -> "CoworldManifest":
        for section in MANIFEST_ROLE_SECTIONS:
            for index, runnable in enumerate(getattr(self, section)):
                if runnable.type != section:
                    raise ValueError(f"{section}.{index}.type must be {section!r}")
        return self


class CoworldEpisodeJobSpec(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        title="Coworld Episode Job Spec",
        json_schema_extra={
            "$schema": SCHEMA_VERSION,
            "description": "Runner-facing request for one Coworld episode.",
        },
    )

    schema_: str | None = Field(default=None, alias="$schema")
    manifest: CoworldManifest
    game_config: dict[str, Any]
    players: list[Annotated[CoworldRunnableSpec, Field(json_schema_extra=_runnable_type_schema("player"))]]
    episode_tags: dict[str, str] = Field(default_factory=dict)
    policy_names: list[str] | None = Field(
        default=None,
        description=(
            "Optional runner metadata with one display name per player slot. "
            "These names stay outside game_config; runners expose them through runner-owned channels."
        ),
    )

    @field_validator("players", mode="after")
    @classmethod
    def normalize_players(cls, players: list[CoworldRunnableSpec]) -> list[CoworldRunnableSpec]:
        return [player.as_runnable_spec() for player in players]

    @model_validator(mode="after")
    def validate_player_lengths(self) -> "CoworldEpisodeJobSpec":
        if self.policy_names is not None and len(self.policy_names) != len(self.players):
            raise ValueError("policy_names must have one entry per player")
        for index, player in enumerate(self.players):
            if player.type != "player":
                raise ValueError(f"players.{index}.type must be 'player'")
        return self

    @property
    def game_runnable(self) -> CoworldRunnableSpec:
        return self.manifest.game.runnable

    @property
    def results_schema(self) -> JsonSchema:
        return self.manifest.game.results_schema

    @property
    def config_schema(self) -> JsonSchema:
        return self.manifest.game.config_schema


def coworld_manifest_schema() -> dict[str, Any]:
    schema = CoworldManifest.model_json_schema(by_alias=True, ref_template="#/$defs/{model}")
    schema["$schema"] = SCHEMA_VERSION
    return schema


def coworld_episode_request_schema() -> dict[str, Any]:
    schema = CoworldEpisodeJobSpec.model_json_schema(by_alias=True, ref_template="#/$defs/{model}")
    schema["$schema"] = SCHEMA_VERSION
    return schema
