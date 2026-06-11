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
_FUTURE_REQUIRED_ROLE_COMMENT = "Optional in the current schema; intended to become required as this role stabilizes."


def _runnable_type_schema(runnable_type: str) -> JsonSchema:
    return {"properties": {"type": {"const": runnable_type}}}


def _role_doc_schema(role: str) -> JsonSchema:
    role_doc = f"docs/roles/{role.upper()}.md"
    role_label = role.capitalize()
    return {
        "markdownDescription": f"See the [{role_label} role]({role_doc}) documentation for this role's contract.",
        "x-coworld-role-doc": role_doc,
    }


def _future_required_role_schema(role: str) -> JsonSchema:
    return {
        **_role_doc_schema(role),
        "$comment": _FUTURE_REQUIRED_ROLE_COMMENT,
        "x-coworld-future-required": True,
    }


class CoworldRunnableSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: CoworldRunnableRole = Field(description="Role contract implemented by this runnable.")
    image: str = Field(description="Docker image reference to run for this role.")
    run: list[str] = Field(
        default_factory=list,
        description="Optional process command overriding the image entrypoint or default command.",
    )
    env: dict[str, str] = Field(
        default_factory=dict,
        description="Public environment variables passed to the runnable. Do not put secrets here.",
    )
    source_url: str | None = Field(
        default=None,
        description="Optional public source repository, directory, or file URL for this runnable.",
    )

    def as_runnable_spec(self) -> CoworldRunnableSpec:
        return CoworldRunnableSpec.model_validate(self.model_dump(include=set(CoworldRunnableSpec.model_fields)))


class CoworldManifestRoleSpec(CoworldRunnableSpec):
    type: CoworldManifestRole = Field(description="Manifest role section this runnable belongs to.")
    id: str = Field(
        min_length=1,
        description="Stable runnable identifier within this manifest. Certification fixtures reference player ids.",
    )
    name: str = Field(min_length=1, description="Human-readable runnable name for CLIs and UIs.")
    description: str = Field(
        min_length=1,
        description="Human-readable summary of what this runnable does.",
    )
    repository_url: str | None = Field(
        default=None,
        description=(
            "Optional Git repository the local optimizer tooling clones and runs. "
            "Used by `coworld optimize` to resolve a game-specific optimizer workbench; "
            "informational for other roles."
        ),
    )


class CoworldTextDoc(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["text"] = Field(description="Document reference kind for inline text.")
    value: str = Field(min_length=1, description="Inline document text, usually Markdown.")


class CoworldUriDoc(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["uri"] = Field(description="Document reference kind for a public HTTP(S) document.")
    value: str = Field(min_length=1, pattern=HTTP_URL_PATTERN, description="Public HTTP(S) URL for the document.")


CoworldDoc = Annotated[CoworldTextDoc | CoworldUriDoc, Field(discriminator="type")]


class CoworldProtocolDocs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    player: CoworldDoc = Field(description="Public player WebSocket protocol documentation.")
    global_: CoworldDoc = Field(alias="global", description="Public global viewer protocol documentation.")


class CoworldDocPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(
        min_length=1,
        description="Stable supplemental document page id.",
    )
    title: str = Field(min_length=1, description="Human-readable page title.")
    content: CoworldDoc = Field(description="Inline or URI-backed page content.")

    @field_validator("id", mode="before")
    @classmethod
    def strip_id_trailing_newlines(cls, value: object) -> object:
        if isinstance(value, str):
            return value.rstrip("\r\n")
        return value


class CoworldDocs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    readme: CoworldDoc = Field(
        description="Required top-level README.md document for game rules, strategy, player guidance, and FAQs.",
    )
    pages: list[CoworldDocPage] = Field(
        default_factory=list,
        description=(
            "Optional public documentation pages. Use game-authored pages for supplemental material; "
            "Softmax leagues may also list a platform-owned play_*.md guide for setup, upload, and submission."
        ),
    )


class CoworldGameManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, description="Short Coworld name.")
    version: str = Field(
        min_length=1,
        description="Coworld package version. Pydantic validation requires a valid PEP 440 version.",
    )
    description: str = Field(min_length=1, description="Human-readable game description surfaced by product UIs.")
    owner: str = Field(min_length=1, description="Maintainer email or handle.")
    config_schema: JsonSchema = Field(
        description=(
            "JSON Schema for runtime game configs. It must require a string-array `tokens` field with minItems and "
            "maxItems bounds; variants and certification configs omit tokens because the runner injects them."
        )
    )
    results_schema: JsonSchema = Field(
        description="JSON Schema for the game-written results artifact. Cross-game consumers require `scores`."
    )
    runnable: Annotated[
        CoworldRunnableSpec,
        Field(
            description="Game container runnable. Its `type` must be `game`.",
            json_schema_extra=_runnable_type_schema("game"),
        ),
    ]
    protocols: CoworldProtocolDocs = Field(description="Protocol documentation for game-owned WebSocket surfaces.")
    docs: CoworldDocs = Field(description="Game-authored documentation surfaced through Coworld tools and UIs.")

    @model_validator(mode="after")
    def validate_version(self) -> "CoworldGameManifest":
        Version(self.version)
        if self.runnable.type != "game":
            raise ValueError("game.runnable.type must be 'game'")
        return self


class CoworldVariant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, description="Stable variant identifier used by CLIs and league configuration.")
    name: str = Field(min_length=1, description="Human-readable variant name.")
    game_config: dict[str, Any] = Field(description="Token-free game config that validates against game.config_schema.")
    description: str = Field(min_length=1, description="Human-readable variant description.")


class CoworldCertificationPlayer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    player_id: str = Field(
        min_length=1,
        description="ID of a bundled player runnable to use for this certification slot.",
    )


class CoworldCertificationFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    game_config: dict[str, Any] = Field(
        description="Token-free game config used for certification and default local episode runs."
    )
    players: list[CoworldCertificationPlayer] = Field(
        min_length=1,
        description="Ordered bundled-player slots for the certification episode.",
    )


class CoworldManifest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        title="Coworld Manifest",
        json_schema_extra={
            "$schema": SCHEMA_VERSION,
            "description": "Schema for a complete game world in the Softmax universe.",
        },
    )

    schema_: str | None = Field(default=None, alias="$schema", description="Optional JSON Schema URI for IDE tooling.")
    game: CoworldGameManifest = Field(
        description="Game runnable and protocol metadata. Role docs: docs/roles/GAME.md.",
        json_schema_extra=_role_doc_schema("game"),
    )
    player: list[CoworldManifestRoleSpec] = Field(
        min_length=1,
        description="Bundled player runnables. Role docs: docs/roles/PLAYER.md.",
        json_schema_extra=_role_doc_schema("player"),
    )
    reporter: list[CoworldManifestRoleSpec] = Field(
        default_factory=list,
        description="Reporter runnables. Optional; include entries when the Coworld ships reporter containers. "
        "Role docs: docs/roles/REPORTER.md.",
        json_schema_extra=_role_doc_schema("reporter"),
    )
    commissioner: list[CoworldManifestRoleSpec] = Field(
        default_factory=list,
        description="Commissioner runnables. Optional. Role docs: docs/roles/COMMISSIONER.md.",
        json_schema_extra=_role_doc_schema("commissioner"),
    )
    grader: list[CoworldManifestRoleSpec] = Field(
        default_factory=list,
        description="Grader runnables. Optional; include entries when the Coworld ships grader containers. "
        "Role docs: docs/roles/GRADER.md.",
        json_schema_extra=_role_doc_schema("grader"),
    )
    diagnoser: list[CoworldManifestRoleSpec] = Field(
        default_factory=list,
        description=(
            "Diagnoser runnables. Optional today, but expected to become required once the diagnoser contract "
            "stabilizes. Role docs: docs/roles/DIAGNOSER.md."
        ),
        json_schema_extra=_future_required_role_schema("diagnoser"),
    )
    optimizer: list[CoworldManifestRoleSpec] = Field(
        default_factory=list,
        description=(
            "Optimizer runnables. Optional today, but expected to become required once the optimizer contract "
            "stabilizes. Role docs: docs/roles/OPTIMIZER.md."
        ),
        json_schema_extra=_future_required_role_schema("optimizer"),
    )
    variants: list[CoworldVariant] = Field(min_length=1, description="Named token-free game configs.")
    certification: CoworldCertificationFixture = Field(
        description="Smoke-test episode used by coworld certify and default local episode runs."
    )

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

    @field_validator("players", mode="after")
    @classmethod
    def normalize_players(cls, players: list[CoworldRunnableSpec]) -> list[CoworldRunnableSpec]:
        return [player.as_runnable_spec() for player in players]

    @model_validator(mode="after")
    def validate_player_types(self) -> "CoworldEpisodeJobSpec":
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
