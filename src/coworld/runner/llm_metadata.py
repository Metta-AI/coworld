from __future__ import annotations

import json
import re
from typing import Annotated, Literal, TypeAlias
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, TypeAdapter

LLM_REQUEST_METADATA_MAX_ENTRIES = 16
LLM_REQUEST_METADATA_MAX_LENGTH = 256
_LLM_REQUEST_METADATA_KEY = re.compile(rf"[A-Za-z0-9\s._:/=+$@#,-]{{1,{LLM_REQUEST_METADATA_MAX_LENGTH}}}")
_LLM_REQUEST_METADATA_VALUE = re.compile(rf"[A-Za-z0-9\s._:/=+$@#,-]{{0,{LLM_REQUEST_METADATA_MAX_LENGTH}}}")

# Stored attribution records retain the historical sidecar origin.
LlmEpisodeMetadataOrigin: TypeAlias = Literal["dispatcher", "coworld_runner", "llm_sidecar", "bedrock_sidecar"]


class CoworldEpisodeLlmMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1"]
    source: Literal["coworld_episode"]
    metadata_origin: LlmEpisodeMetadataOrigin
    episode_request_id: UUID | None = None
    job_request_id: UUID
    role: Literal["game", "player"]
    slot: str = Field(min_length=1)
    image_digest: str = Field(min_length=1)


class CoworldPlayLlmMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1"]
    openrouter_lane: str = Field(min_length=1)
    openrouter_lane_expires_at: AwareDatetime
    source: Literal["coworld_play"]
    metadata_origin: Literal["llm_sidecar"]
    play_session_id: str = Field(min_length=1)
    coworld_id: str = Field(min_length=1)
    role: Literal["game", "player"]
    slot: str = Field(min_length=1)
    image_digest: str = Field(min_length=1)
    policy_version_id: str | None = None


class CoworldReplayLlmMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1"]
    openrouter_lane: str = Field(min_length=1)
    openrouter_lane_expires_at: AwareDatetime
    source: Literal["coworld_replay"]
    metadata_origin: Literal["llm_sidecar"]
    runtime_resource_name: str = Field(min_length=1)
    coworld_id: str = Field(min_length=1)
    role: Literal["game"] = "game"
    slot: Literal["game"] = "game"
    image_digest: str = Field(min_length=1)


CoworldLlmMetadata: TypeAlias = Annotated[
    CoworldEpisodeLlmMetadata | CoworldPlayLlmMetadata | CoworldReplayLlmMetadata,
    Field(discriminator="source"),
]
_COWORLD_LLM_METADATA_ADAPTER = TypeAdapter(CoworldLlmMetadata)


def parse_coworld_llm_metadata(serialized: str) -> CoworldLlmMetadata:
    return _COWORLD_LLM_METADATA_ADAPTER.validate_json(serialized)


class ReporterRunLlmMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1"]
    source: Literal["reporter_run"]
    metadata_origin: Literal["reporter_bureau"]
    reporter_run_id: str = Field(min_length=1)
    reporter_version_id: str = Field(min_length=1)
    billed_user_id: str = Field(min_length=1)


class CompactionLlmMetadata(BaseModel):
    """One league-funded compaction, identified by its committed reservation lease."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1"] = "1"
    source: Literal["scratchpad_compaction"] = "scratchpad_compaction"
    metadata_origin: Literal["host_client"] = "host_client"
    lease_token: UUID
    league_id: str = Field(min_length=1)
    coworld_name: str = Field(min_length=1)


class HostLlmMetadata(BaseModel):
    """Platform-funded inference outside an episode or reporter run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1"] = "1"
    source: Literal["host"] = "host"
    metadata_origin: Literal["host_client"] = "host_client"
    caller: Literal["sql_assistant", "campaign_strategist", "website", "internal_tool"]


LlmRequestMetadata: TypeAlias = Annotated[
    CoworldEpisodeLlmMetadata
    | CoworldPlayLlmMetadata
    | CoworldReplayLlmMetadata
    | ReporterRunLlmMetadata
    | HostLlmMetadata
    | CompactionLlmMetadata,
    Field(discriminator="source"),
]

_LLM_REQUEST_METADATA_ADAPTER = TypeAdapter(LlmRequestMetadata)


def llm_request_metadata(metadata: LlmRequestMetadata) -> dict[str, str]:
    """Return the canonical flat string map within the attribution size limits."""
    values = metadata.model_dump(mode="json", exclude_none=True)
    if len(values) > LLM_REQUEST_METADATA_MAX_ENTRIES:
        raise ValueError(
            f"LLM request metadata has {len(values)} entries; maximum is {LLM_REQUEST_METADATA_MAX_ENTRIES}"
        )
    for key, value in values.items():
        if _LLM_REQUEST_METADATA_KEY.fullmatch(key) is None:
            raise ValueError(f"Invalid LLM request metadata key: {key!r}")
        if _LLM_REQUEST_METADATA_VALUE.fullmatch(value) is None:
            raise ValueError(f"Invalid LLM request metadata value for {key!r}: {value!r}")
    return values


def serialize_llm_request_metadata(metadata: LlmRequestMetadata) -> str:
    """Serialize one canonical attribution map for request metadata and environment variables."""
    return json.dumps(llm_request_metadata(metadata), sort_keys=True, separators=(",", ":"))


def parse_llm_request_metadata(serialized: str) -> LlmRequestMetadata:
    return _LLM_REQUEST_METADATA_ADAPTER.validate_json(serialized)
