from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

_STATE_MAX_BYTES = 10 * 1024 * 1024


class LeagueInfo(BaseModel):
    id: UUID
    commissioner_key: str | None = None
    commissioner_config: dict[str, Any] | None = None


class DivisionInfo(BaseModel):
    id: UUID
    name: str
    level: int
    type: str = "competition"


class MembershipInfo(BaseModel):
    id: UUID
    league_id: UUID
    division_id: UUID
    policy_version_id: UUID
    player_id: str | None = None
    status: str = "competing"
    substatus: str | None = None


class RecentResult(BaseModel):
    round_id: UUID
    division_id: UUID
    round_number: int
    policy_version_id: UUID
    rank: int
    score: float


class VariantInfo(BaseModel):
    id: str
    name: str
    game_config: dict[str, Any]
    num_agents: int = Field(gt=0)


class EpisodeRequest(BaseModel):
    request_id: str
    variant_id: str
    policy_version_ids: list[UUID]
    seed: int | None = None
    tags: dict[str, str] = Field(default_factory=dict)


class EpisodeScore(BaseModel):
    policy_version_id: UUID
    player_id: str | None = None
    score: float


class RankingEntry(BaseModel):
    policy_version_id: UUID
    player_id: str | None = None
    rank: int
    score: float
    result_metadata: dict[str, Any] = Field(default_factory=dict)


class DivisionRanking(BaseModel):
    division_id: UUID
    rankings: list[RankingEntry]


class GraduationChange(BaseModel):
    membership_id: UUID
    to_division_id: UUID
    reason: str


class MembershipChange(BaseModel):
    membership_id: UUID
    from_division_id: UUID
    to_division_id: UUID | None = None
    is_active: bool = True
    reason: str


class StageConfig(BaseModel):
    label: str = "Round"
    num_episodes: int = Field(default=1, gt=0)
    min_episodes_per_entrant: int | None = Field(default=None, gt=0)


class RoundConfig(BaseModel):
    mock_scores: dict[UUID, float] | None = None
    stages: list[StageConfig] | None = None
    entrant_policy_version_ids: list[UUID] | None = None


class RoundInfo(BaseModel):
    id: UUID
    public_id: str | None = None
    division_id: UUID
    round_number: int
    status: str
    round_config: dict[str, Any] = Field(default_factory=dict)
    created_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None


class RoundResultInfo(BaseModel):
    round_id: UUID
    policy_version_id: UUID
    rank: int
    score: float
    result_metadata: dict[str, Any] = Field(default_factory=dict)


class LeaderboardRoundResultInfo(RoundResultInfo):
    player_id: str
    player_name: str | None = None


class RoundSpec(BaseModel):
    division_id: UUID
    round_config: RoundConfig
    execution_backend: str = "mock"
    notes: str | None = None


class DivisionLeaderboardEntry(BaseModel):
    player_id: str
    player_name: str | None = None
    rank: int
    score: float
    rounds_played: int
    policy_version_ids: set[UUID] = Field(default_factory=set)
    recent_rounds: list[dict[str, Any]] | None = None


class DivisionDescription(BaseModel):
    round_schedule: str | None = None
    next_round: str | None = None
    round_structure: str | None = None
    leaderboard_rules: str | None = None
    scoring_mechanics: str | None = None


class RoundStart(BaseModel):
    round_id: UUID
    round_number: int
    league: LeagueInfo
    divisions: list[DivisionInfo]
    memberships: list[MembershipInfo]
    recent_results: list[RecentResult]
    variants: list[VariantInfo]
    state: Any = None

    def to_json(self) -> dict[str, Any]:
        data = self.model_dump(mode="json")
        data["type"] = "round_start"
        return data


class EpisodeAccepted(BaseModel):
    request_ids: list[str]

    def to_json(self) -> dict[str, Any]:
        data = self.model_dump(mode="json")
        data["type"] = "episodes_accepted"
        return data


class EpisodesRejected(BaseModel):
    request_ids: list[str]
    errors: dict[str, str]

    def to_json(self) -> dict[str, Any]:
        data = self.model_dump(mode="json")
        data["type"] = "episodes_rejected"
        return data


class EpisodeResult(BaseModel):
    request_id: str
    scores: list[EpisodeScore]
    game_results: dict[str, Any] | None = None

    def to_json(self) -> dict[str, Any]:
        data = self.model_dump(mode="json")
        data["type"] = "episode_result"
        return data


class EpisodeFailed(BaseModel):
    request_id: str
    error: str

    def to_json(self) -> dict[str, Any]:
        data = self.model_dump(mode="json")
        data["type"] = "episode_failed"
        return data


class RoundAbort(BaseModel):
    reason: str

    def to_json(self) -> dict[str, Any]:
        data = self.model_dump(mode="json")
        data["type"] = "round_abort"
        return data


class ScheduleEpisodes(BaseModel):
    episodes: list[EpisodeRequest]

    def to_json(self) -> dict[str, Any]:
        data = self.model_dump(mode="json")
        data["type"] = "schedule_episodes"
        return data


class RoundComplete(BaseModel):
    results: list[DivisionRanking] = Field(default_factory=list)
    graduation_changes: list[GraduationChange] = Field(default_factory=list)
    membership_changes: list[MembershipChange] = Field(default_factory=list)
    round_display: dict[str, Any] | None = None
    state: Any = None

    @field_validator("state")
    @classmethod
    def validate_state_size(cls, value: Any) -> Any:
        if value is None:
            return value
        serialized = json.dumps(value)
        size_bytes = len(serialized.encode())
        if size_bytes > _STATE_MAX_BYTES:
            raise ValueError(f"state must not exceed 10 MB (got {size_bytes} bytes)")
        return value

    def to_json(self) -> dict[str, Any]:
        data = self.model_dump(mode="json")
        data["type"] = "round_complete"
        return data


class ScheduleRoundsRequest(BaseModel):
    league: LeagueInfo
    divisions: list[DivisionInfo]
    active_memberships: list[MembershipInfo]
    recent_rounds: list[RoundInfo]

    def to_json(self) -> dict[str, Any]:
        data = self.model_dump(mode="json")
        data["type"] = "schedule_rounds_request"
        return data


class ScheduleRoundsResponse(BaseModel):
    rounds: list[RoundSpec] = Field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        data = self.model_dump(mode="json")
        data["type"] = "schedule_rounds_response"
        return data


class RankDivisionRequest(BaseModel):
    league: LeagueInfo
    division: DivisionInfo
    completed_rounds: list[RoundInfo]
    recent_rounds: list[RoundInfo]
    round_results: list[LeaderboardRoundResultInfo]

    def to_json(self) -> dict[str, Any]:
        data = self.model_dump(mode="json")
        data["type"] = "rank_division_request"
        return data


class RankDivisionResponse(BaseModel):
    rankings: list[DivisionLeaderboardEntry] = Field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        data = self.model_dump(mode="json")
        data["type"] = "rank_division_response"
        return data


class DescribeDivisionRequest(BaseModel):
    league: LeagueInfo
    division: DivisionInfo
    active_memberships: list[MembershipInfo]
    recent_rounds: list[RoundInfo]

    def to_json(self) -> dict[str, Any]:
        data = self.model_dump(mode="json")
        data["type"] = "describe_division_request"
        return data


class DescribeDivisionResponse(BaseModel):
    description: DivisionDescription

    def to_json(self) -> dict[str, Any]:
        data = self.model_dump(mode="json")
        data["type"] = "describe_division_response"
        return data


class RoundCompletedRequest(BaseModel):
    league: LeagueInfo
    division: DivisionInfo
    all_divisions: list[DivisionInfo]
    round_config: RoundConfig
    round_results: list[RoundResultInfo]
    division_memberships: list[MembershipInfo]
    recent_results: list[RoundResultInfo]
    commissioner_config: dict[str, Any] | None = None

    def to_json(self) -> dict[str, Any]:
        data = self.model_dump(mode="json")
        data["type"] = "round_completed_request"
        return data


class EpisodeCompletedRequest(BaseModel):
    round_start: RoundStart
    episode_result: EpisodeResult | None = None
    episode_failed: EpisodeFailed | None = None
    completed_episode_results: list[EpisodeResult] = Field(default_factory=list)
    failed_episodes: list[EpisodeFailed] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_completed_event(self) -> EpisodeCompletedRequest:
        if (self.episode_result is None) == (self.episode_failed is None):
            raise ValueError("exactly one of episode_result or episode_failed must be set")
        return self

    def to_json(self) -> dict[str, Any]:
        data = self.model_dump(mode="json")
        data["type"] = "episode_completed_request"
        return data


class RoundCompletedResponse(BaseModel):
    membership_changes: list[MembershipChange] = Field(default_factory=list)
    follow_up_rounds: list[RoundSpec] = Field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        data = self.model_dump(mode="json")
        data["type"] = "round_completed_response"
        return data


class EpisodeCompletedResponse(BaseModel):
    episodes: list[EpisodeRequest] = Field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        data = self.model_dump(mode="json")
        data["type"] = "episode_completed_response"
        return data


PlatformMessage = (
    RoundStart
    | EpisodeAccepted
    | EpisodesRejected
    | EpisodeResult
    | EpisodeFailed
    | RoundAbort
    | ScheduleRoundsRequest
    | RankDivisionRequest
    | DescribeDivisionRequest
    | RoundCompletedRequest
    | EpisodeCompletedRequest
)

CommissionerMessageType = (
    ScheduleEpisodes
    | RoundComplete
    | ScheduleRoundsResponse
    | RankDivisionResponse
    | DescribeDivisionResponse
    | RoundCompletedResponse
    | EpisodeCompletedResponse
)

_COMMISSIONER_MESSAGE_TYPES: dict[str, type[CommissionerMessageType]] = {
    "schedule_episodes": ScheduleEpisodes,
    "round_complete": RoundComplete,
    "schedule_rounds_response": ScheduleRoundsResponse,
    "rank_division_response": RankDivisionResponse,
    "describe_division_response": DescribeDivisionResponse,
    "round_completed_response": RoundCompletedResponse,
    "episode_completed_response": EpisodeCompletedResponse,
}


class CommissionerMessage:
    @staticmethod
    def from_json(data: dict[str, Any]) -> CommissionerMessageType:
        msg_type = data["type"]
        cls = _COMMISSIONER_MESSAGE_TYPES.get(msg_type)
        if cls is None:
            raise ValueError(f"Unknown commissioner message type: {msg_type!r}")
        return cls.model_validate({key: value for key, value in data.items() if key != "type"})
