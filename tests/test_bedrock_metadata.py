from uuid import UUID

import pytest
from pydantic import ValidationError

from coworld.runner.bedrock_metadata import (
    BEDROCK_REQUEST_METADATA_MAX_ENTRIES,
    CoworldEpisodeBedrockMetadata,
    ReporterRunBedrockMetadata,
    bedrock_request_metadata,
    parse_bedrock_request_metadata,
    serialize_bedrock_request_metadata,
)

EPISODE_REQUEST_ID = UUID("11111111-1111-1111-1111-111111111111")
JOB_REQUEST_ID = UUID("22222222-2222-2222-2222-222222222222")


def test_episode_metadata_serializes_to_stable_flat_strings() -> None:
    metadata = CoworldEpisodeBedrockMetadata(
        schema_version="1",
        source="coworld_episode",
        metadata_origin="bedrock_sidecar",
        episode_request_id=EPISODE_REQUEST_ID,
        job_request_id=JOB_REQUEST_ID,
        role="player",
        slot="3",
        image_digest="sha256:abc123",
    )

    assert bedrock_request_metadata(metadata) == {
        "schema_version": "1",
        "source": "coworld_episode",
        "metadata_origin": "bedrock_sidecar",
        "episode_request_id": str(EPISODE_REQUEST_ID),
        "job_request_id": str(JOB_REQUEST_ID),
        "role": "player",
        "slot": "3",
        "image_digest": "sha256:abc123",
    }
    serialized = serialize_bedrock_request_metadata(metadata)
    assert serialized == (
        '{"episode_request_id":"11111111-1111-1111-1111-111111111111","image_digest":"sha256:abc123",'
        '"job_request_id":"22222222-2222-2222-2222-222222222222","metadata_origin":"bedrock_sidecar",'
        '"role":"player","schema_version":"1","slot":"3","source":"coworld_episode"}'
    )
    assert parse_bedrock_request_metadata(serialized) == metadata
    assert len(bedrock_request_metadata(metadata)) <= BEDROCK_REQUEST_METADATA_MAX_ENTRIES


def test_persistent_runtime_metadata_omits_absent_episode_request_id() -> None:
    metadata = CoworldEpisodeBedrockMetadata(
        schema_version="1",
        source="coworld_episode",
        metadata_origin="dispatcher",
        job_request_id=JOB_REQUEST_ID,
        role="game",
        slot="game",
        image_digest="sha256:abc123",
    )

    assert "episode_request_id" not in bedrock_request_metadata(metadata)
    assert parse_bedrock_request_metadata(serialize_bedrock_request_metadata(metadata)) == metadata


def test_reporter_metadata_round_trips_as_reporter_variant() -> None:
    metadata = ReporterRunBedrockMetadata(
        schema_version="1",
        source="reporter_run",
        metadata_origin="reporter_bureau",
        reporter_run_id="rr_123",
        reporter_version_id="rv_456",
        billed_user_id="user_789",
    )

    parsed = parse_bedrock_request_metadata(serialize_bedrock_request_metadata(metadata))

    assert parsed == metadata
    assert isinstance(parsed, ReporterRunBedrockMetadata)


def test_serializer_accepts_full_bedrock_metadata_punctuation() -> None:
    metadata = ReporterRunBedrockMetadata(
        schema_version="1",
        source="reporter_run",
        metadata_origin="reporter_bureau",
        reporter_run_id="rr_123,#",
        reporter_version_id="rv_456",
        billed_user_id="user_789",
    )

    assert bedrock_request_metadata(metadata)["reporter_run_id"] == "rr_123,#"


@pytest.mark.parametrize("missing", ["schema_version", "source"])
def test_protocol_identity_fields_are_required(missing: str) -> None:
    values = {
        "schema_version": "1",
        "source": "reporter_run",
        "metadata_origin": "reporter_bureau",
        "reporter_run_id": "rr_123",
        "reporter_version_id": "rv_456",
        "billed_user_id": "user_789",
    }
    del values[missing]

    with pytest.raises(ValidationError):
        ReporterRunBedrockMetadata.model_validate(values)


def test_metadata_variants_are_frozen_and_forbid_unknown_fields() -> None:
    metadata = ReporterRunBedrockMetadata(
        schema_version="1",
        source="reporter_run",
        metadata_origin="reporter_bureau",
        reporter_run_id="rr_123",
        reporter_version_id="rv_456",
        billed_user_id="user_789",
    )

    with pytest.raises(ValidationError):
        metadata.reporter_run_id = "rr_changed"
    with pytest.raises(ValidationError):
        ReporterRunBedrockMetadata.model_validate({**metadata.model_dump(), "coworld": "mutable display name"})


@pytest.mark.parametrize(
    "image_digest",
    [
        "x" * 257,
        "sha256:invalid?digest",
    ],
)
def test_serializer_rejects_values_bedrock_would_reject(image_digest: str) -> None:
    metadata = CoworldEpisodeBedrockMetadata(
        schema_version="1",
        source="coworld_episode",
        metadata_origin="dispatcher",
        episode_request_id=EPISODE_REQUEST_ID,
        job_request_id=JOB_REQUEST_ID,
        role="game",
        slot="game",
        image_digest=image_digest,
    )

    with pytest.raises(ValueError, match="Invalid Bedrock request metadata value"):
        serialize_bedrock_request_metadata(metadata)
