from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

_STATE_MAX_BYTES = 10 * 1024 * 1024


class LeagueInfo(BaseModel):
    id: UUID
    commissioner_config: dict[str, Any] | None = None


class DivisionInfo(BaseModel):
    id: UUID
    name: str
    level: int


class MembershipInfo(BaseModel):
    id: UUID
    division_id: UUID
    policy_version_id: UUID
    player_id: str | None = None
    is_champion: bool = False


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


PlatformMessage = RoundStart | EpisodeAccepted | EpisodesRejected | EpisodeResult | EpisodeFailed | RoundAbort


class ScheduleEpisodes(BaseModel):
    episodes: list[EpisodeRequest]

    def to_json(self) -> dict[str, Any]:
        data = self.model_dump(mode="json")
        data["type"] = "schedule_episodes"
        return data


class RoundComplete(BaseModel):
    results: list[DivisionRanking] = Field(default_factory=list)
    graduation_changes: list[GraduationChange] = Field(default_factory=list)
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


_COMMISSIONER_MESSAGE_TYPES: dict[str, type[ScheduleEpisodes | RoundComplete]] = {
    "schedule_episodes": ScheduleEpisodes,
    "round_complete": RoundComplete,
}


class CommissionerMessage:
    @staticmethod
    def from_json(data: dict[str, Any]) -> ScheduleEpisodes | RoundComplete:
        msg_type = data["type"]
        cls = _COMMISSIONER_MESSAGE_TYPES.get(msg_type)
        if cls is None:
            raise ValueError(f"Unknown commissioner message type: {msg_type!r}")
        return cls.model_validate({key: value for key, value in data.items() if key != "type"})
