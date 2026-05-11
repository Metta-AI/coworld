from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "https://json-schema.org/draft/2020-12/schema"
JsonSchema = dict[str, Any]


class CoworldRunnableSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")

    image: str
    run: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)


class CoworldPlayerSpec(CoworldRunnableSpec):
    pass


class CoworldDeclaredRunnableSpec(CoworldRunnableSpec):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)


class CoworldGameRunnableSpec(CoworldRunnableSpec):
    type: Literal["game"] = "game"


class CoworldDeclaredRoleSpec(CoworldDeclaredRunnableSpec):
    type: Literal["player", "grader", "reporter", "commissioner", "diagnoser", "optimizer"]


class CoworldProtocolDocs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    player: str = Field(min_length=1)
    global_: str = Field(alias="global", min_length=1)


class CoworldDocPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    content: str = Field(min_length=1)


class CoworldDocs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    readme: str | None = Field(default=None, min_length=1)
    pages: list[CoworldDocPage] = Field(default_factory=list)


class CoworldGameManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    description: str = Field(min_length=1)
    owner: str = Field(min_length=1)
    config_schema: JsonSchema
    results_schema: JsonSchema
    runnable: CoworldGameRunnableSpec
    protocols: CoworldProtocolDocs
    docs: CoworldDocs | None = None


class CoworldVariant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    game_config: dict[str, Any]
    parent_id: str | None = Field(default=None, min_length=1)
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
    game: CoworldGameManifest
    player: list[CoworldDeclaredRoleSpec] = Field(min_length=1)
    grader: list[CoworldDeclaredRoleSpec] = Field(default_factory=list)
    reporter: list[CoworldDeclaredRoleSpec] = Field(default_factory=list)
    commissioner: list[CoworldDeclaredRoleSpec] = Field(default_factory=list)
    diagnoser: list[CoworldDeclaredRoleSpec] = Field(default_factory=list)
    optimizer: list[CoworldDeclaredRoleSpec] = Field(default_factory=list)
    variants: list[CoworldVariant] = Field(min_length=1)
    certification: CoworldCertificationFixture


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
    players: list[CoworldPlayerSpec]
    episode_tags: dict[str, str] = Field(default_factory=dict)
    policy_names: list[str] | None = None

    @model_validator(mode="after")
    def validate_player_lengths(self) -> "CoworldEpisodeJobSpec":
        if self.policy_names is not None and len(self.policy_names) != len(self.players):
            raise ValueError("policy_names must have one entry per player")
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
