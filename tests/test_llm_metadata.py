from uuid import UUID

import pytest
from pydantic import ValidationError

from coworld.runner.llm_metadata import (
    LLM_REQUEST_METADATA_MAX_ENTRIES,
    CoworldEpisodeLlmMetadata,
    CoworldPersistentLlmMetadata,
    CoworldPlayLlmMetadata,
    CoworldReplayLlmMetadata,
    HostLlmMetadata,
    LlmEpisodeMetadataOrigin,
    ReporterRunLlmMetadata,
    llm_request_metadata,
    parse_llm_request_metadata,
    serialize_llm_request_metadata,
)

EPISODE_REQUEST_ID = UUID("11111111-1111-1111-1111-111111111111")
JOB_REQUEST_ID = UUID("22222222-2222-2222-2222-222222222222")


@pytest.mark.parametrize("origin", ["llm_sidecar", "bedrock_sidecar"])
def test_episode_metadata_serializes_to_stable_flat_strings(origin: LlmEpisodeMetadataOrigin) -> None:
    metadata = CoworldEpisodeLlmMetadata(
        schema_version="1",
        source="coworld_episode",
        metadata_origin=origin,
        episode_request_id=EPISODE_REQUEST_ID,
        job_request_id=JOB_REQUEST_ID,
        role="player",
        slot="3",
        image_digest="sha256:abc123",
    )

    assert llm_request_metadata(metadata) == {
        "schema_version": "1",
        "source": "coworld_episode",
        "metadata_origin": origin,
        "episode_request_id": str(EPISODE_REQUEST_ID),
        "job_request_id": str(JOB_REQUEST_ID),
        "role": "player",
        "slot": "3",
        "image_digest": "sha256:abc123",
    }
    serialized = serialize_llm_request_metadata(metadata)
    assert serialized == (
        '{"episode_request_id":"11111111-1111-1111-1111-111111111111","image_digest":"sha256:abc123",'
        f'"job_request_id":"22222222-2222-2222-2222-222222222222","metadata_origin":"{origin}",'
        '"role":"player","schema_version":"1","slot":"3","source":"coworld_episode"}'
    )
    assert parse_llm_request_metadata(serialized) == metadata
    assert len(llm_request_metadata(metadata)) <= LLM_REQUEST_METADATA_MAX_ENTRIES


@pytest.mark.parametrize(("role", "slot"), [("game", "game"), ("player", "0")])
def test_persistent_metadata_preserves_launch_identity_without_an_episode(role, slot) -> None:
    metadata = CoworldPersistentLlmMetadata(
        schema_version="1",
        source="coworld_persistent",
        metadata_origin="llm_sidecar",
        runtime_id=JOB_REQUEST_ID,
        runtime_generation="7",
        league_id="league_original",
        player_id="player_original",
        policy_version_id=str(EPISODE_REQUEST_ID),
        coworld_id="cw_original",
        role=role,
        slot=slot,
        image_digest="sha256:abc123",
        openrouter_lane="persistent:7",
        openrouter_lane_expires_at="2099-01-01T00:00:00Z",
    )
    values = llm_request_metadata(metadata)
    assert len(values) == 14
    assert all(isinstance(value, str) for value in values.values())
    assert parse_llm_request_metadata(serialize_llm_request_metadata(metadata)) == metadata
    for foreign in ("job_request_id", "episode_request_id", "play_session_id"):
        with pytest.raises(ValidationError):
            CoworldPersistentLlmMetadata.model_validate(values | {foreign: str(JOB_REQUEST_ID)})
    for missing in ("runtime_id", "runtime_generation", "league_id", "player_id", "policy_version_id"):
        with pytest.raises(ValidationError):
            CoworldPersistentLlmMetadata.model_validate({k: v for k, v in values.items() if k != missing})
    with pytest.raises(ValidationError):
        CoworldPersistentLlmMetadata.model_validate(values | {"runtime_generation": "0"})


def test_reporter_metadata_round_trips_as_reporter_variant() -> None:
    metadata = ReporterRunLlmMetadata(
        schema_version="1",
        source="reporter_run",
        metadata_origin="reporter_bureau",
        reporter_run_id="rr_123",
        reporter_version_id="rv_456",
        billed_user_id="user_789",
    )

    parsed = parse_llm_request_metadata(serialize_llm_request_metadata(metadata))

    assert parsed == metadata
    assert isinstance(parsed, ReporterRunLlmMetadata)


def test_serializer_accepts_metadata_punctuation() -> None:
    metadata = ReporterRunLlmMetadata(
        schema_version="1",
        source="reporter_run",
        metadata_origin="reporter_bureau",
        reporter_run_id="rr_123,#",
        reporter_version_id="rv_456",
        billed_user_id="user_789",
    )

    assert llm_request_metadata(metadata)["reporter_run_id"] == "rr_123,#"


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
        ReporterRunLlmMetadata.model_validate(values)


def test_metadata_variants_are_frozen_and_forbid_unknown_fields() -> None:
    metadata = ReporterRunLlmMetadata(
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
        ReporterRunLlmMetadata.model_validate({**metadata.model_dump(), "coworld": "mutable display name"})


@pytest.mark.parametrize(
    "image_digest",
    [
        "x" * 257,
        "sha256:invalid?digest",
    ],
)
def test_serializer_rejects_invalid_metadata_values(image_digest: str) -> None:
    metadata = CoworldEpisodeLlmMetadata(
        schema_version="1",
        source="coworld_episode",
        metadata_origin="dispatcher",
        episode_request_id=EPISODE_REQUEST_ID,
        job_request_id=JOB_REQUEST_ID,
        role="game",
        slot="game",
        image_digest=image_digest,
    )

    with pytest.raises(ValueError, match="Invalid LLM request metadata value"):
        serialize_llm_request_metadata(metadata)


@pytest.mark.parametrize("source", ["coworld_play", "coworld_replay"])
def test_hosted_runtime_metadata_has_real_identity_without_episode_ids(source: str) -> None:
    if source == "coworld_play":
        metadata = CoworldPlayLlmMetadata(
            schema_version="1",
            source="coworld_play",
            metadata_origin="llm_sidecar",
            openrouter_lane="shared-lane",
            openrouter_lane_expires_at="2099-01-01T00:00:00Z",
            play_session_id="ps_123",
            coworld_id="cow_123",
            role="player",
            slot="2",
            image_digest="sha256:player",
            policy_version_id="pv_123",
        )
    else:
        metadata = CoworldReplayLlmMetadata(
            schema_version="1",
            source="coworld_replay",
            metadata_origin="llm_sidecar",
            openrouter_lane="shared-lane",
            openrouter_lane_expires_at="2099-01-01T00:00:00Z",
            runtime_resource_name="coworld-replay-123",
            coworld_id="cow_123",
            image_digest="sha256:game",
        )
    values = llm_request_metadata(metadata)
    assert "job_request_id" not in values
    assert "episode_request_id" not in values
    assert "billed_user_id" not in values
    assert parse_llm_request_metadata(serialize_llm_request_metadata(metadata)) == metadata
    with pytest.raises(ValidationError):
        type(metadata).model_validate({**values, "job_request_id": str(JOB_REQUEST_ID)})


@pytest.mark.parametrize("caller", ["sql_assistant", "campaign_strategist", "website", "internal_tool"])
def test_host_metadata_round_trips_without_episode_or_payer(caller: str) -> None:
    metadata = HostLlmMetadata.model_validate({"caller": caller})
    assert parse_llm_request_metadata(serialize_llm_request_metadata(metadata)) == metadata
    assert llm_request_metadata(metadata) == {
        "schema_version": "1",
        "source": "host",
        "metadata_origin": "host_client",
        "caller": caller,
    }
