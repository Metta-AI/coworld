from __future__ import annotations

from typing import Annotated, Any, Literal

from packaging.version import Version
from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "https://json-schema.org/draft/2020-12/schema"
HTTP_URL_PATTERN = r"^https?://"
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
    runnable: CoworldGameRunnableSpec
    protocols: CoworldProtocolDocs
    docs: CoworldDocs | None = None

    @model_validator(mode="after")
    def validate_version(self) -> "CoworldGameManifest":
        Version(self.version)
        return self


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
    player: list[CoworldDeclaredRoleSpec] = Field(
        min_length=1,
        description="Bundled player runnables that can connect to the game and play an episode.",
    )
    grader: list[CoworldDeclaredRoleSpec] = Field(
        default_factory=list,
        description="Optional grader runnables. Use an empty array when no grader is bundled.",
    )
    reporter: list[CoworldDeclaredRoleSpec] = Field(
        default_factory=list,
        description="Optional reporter runnables. Use an empty array when no reporter is bundled.",
    )
    commissioner: list[CoworldDeclaredRoleSpec] = Field(
        default_factory=list,
        description="Optional commissioner runnables. Use an empty array when no commissioner is bundled.",
    )
    diagnoser: list[CoworldDeclaredRoleSpec] = Field(
        default_factory=list,
        description="Optional diagnoser runnables. Use an empty array when no diagnoser is bundled.",
    )
    optimizer: list[CoworldDeclaredRoleSpec] = Field(
        default_factory=list,
        description="Optional optimizer runnables. Use an empty array when no optimizer is bundled.",
    )
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
