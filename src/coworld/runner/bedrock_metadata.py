from __future__ import annotations

import json
import re
from typing import Annotated, Literal, TypeAlias
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

BEDROCK_REQUEST_METADATA_MAX_ENTRIES = 16
BEDROCK_REQUEST_METADATA_MAX_LENGTH = 256
_BEDROCK_REQUEST_METADATA_KEY = re.compile(
    rf"[A-Za-z0-9\s._:/=+$@#,-]{{1,{BEDROCK_REQUEST_METADATA_MAX_LENGTH}}}"
)
_BEDROCK_REQUEST_METADATA_VALUE = re.compile(
    rf"[A-Za-z0-9\s._:/=+$@#,-]{{0,{BEDROCK_REQUEST_METADATA_MAX_LENGTH}}}"
)

BedrockEpisodeMetadataOrigin: TypeAlias = Literal["dispatcher", "coworld_runner", "bedrock_sidecar"]


class CoworldEpisodeBedrockMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1"]
    source: Literal["coworld_episode"]
    metadata_origin: BedrockEpisodeMetadataOrigin
    episode_request_id: UUID
    job_request_id: UUID
    role: Literal["game", "player"]
    slot: str = Field(min_length=1)
    image_digest: str = Field(min_length=1)


class ReporterRunBedrockMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1"]
    source: Literal["reporter_run"]
    metadata_origin: Literal["reporter_bureau"]
    reporter_run_id: str = Field(min_length=1)
    reporter_version_id: str = Field(min_length=1)
    billed_user_id: str = Field(min_length=1)


BedrockRequestMetadata: TypeAlias = Annotated[
    CoworldEpisodeBedrockMetadata | ReporterRunBedrockMetadata,
    Field(discriminator="source"),
]

_BEDROCK_REQUEST_METADATA_ADAPTER = TypeAdapter(BedrockRequestMetadata)


def bedrock_request_metadata(metadata: BedrockRequestMetadata) -> dict[str, str]:
    """Return the Bedrock wire map after enforcing the service's metadata limits."""
    values = metadata.model_dump(mode="json")
    if len(values) > BEDROCK_REQUEST_METADATA_MAX_ENTRIES:
        raise ValueError(
            f"Bedrock request metadata has {len(values)} entries; maximum is {BEDROCK_REQUEST_METADATA_MAX_ENTRIES}"
        )
    for key, value in values.items():
        if _BEDROCK_REQUEST_METADATA_KEY.fullmatch(key) is None:
            raise ValueError(f"Invalid Bedrock request metadata key: {key!r}")
        if _BEDROCK_REQUEST_METADATA_VALUE.fullmatch(value) is None:
            raise ValueError(f"Invalid Bedrock request metadata value for {key!r}: {value!r}")
    return values


def serialize_bedrock_request_metadata(metadata: BedrockRequestMetadata) -> str:
    """Serialize one canonical map for Converse bodies, InvokeModel headers, and env."""
    return json.dumps(bedrock_request_metadata(metadata), sort_keys=True, separators=(",", ":"))


def parse_bedrock_request_metadata(serialized: str) -> BedrockRequestMetadata:
    return _BEDROCK_REQUEST_METADATA_ADAPTER.validate_json(serialized)
