from __future__ import annotations

from datetime import datetime
from typing import Any, Self
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, TypeAdapter, computed_field


class CoworldAPIModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class PolicyPublic(CoworldAPIModel):
    id: UUID
    name: str


class PolicyVersionPublic(CoworldAPIModel):
    id: UUID
    policy: PolicyPublic
    version: int
    player_id: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def label(self) -> str:
        return f"{self.policy.name}:v{self.version}"


class PlayerPublic(CoworldAPIModel):
    id: str
    name: str | None = None
    avatar_url: str | None = None


class GamePublic(CoworldAPIModel):
    id: str
    name: str
    slug: str | None = None
    coworld_name: str | None = None
    coworld_id: str | None = None
    description: str | None = None
    created_at: datetime


class LeaguePublic(CoworldAPIModel):
    id: str
    name: str
    slug: str | None = None
    game: GamePublic
    commissioner_key: str | None = None
    public: bool = False
    hidden: bool = False
    created_at: datetime


class DivisionCommissionerDescriptionPublic(CoworldAPIModel):
    round_schedule: str | None = None
    next_round: str | None = None
    round_structure: str | None = None
    leaderboard_rules: str | None = None


class DivisionPublic(CoworldAPIModel):
    id: str
    name: str
    level: int
    league: LeaguePublic
    description: str | None = None
    commissioner_description: DivisionCommissionerDescriptionPublic | None = None
    created_at: datetime


class DivisionLadderEntryPublic(CoworldAPIModel):
    id: str
    name: str
    level: int
    member_count: int


class LeaguePolicyMembershipPublic(CoworldAPIModel):
    id: str
    is_active: bool
    is_champion: bool
    start_time: datetime
    end_time: datetime | None = None
    league: LeaguePublic
    division: DivisionPublic
    policy_version: PolicyVersionPublic
    player: PlayerPublic | None = None
    created_at: datetime


class LeagueSubmissionPublic(CoworldAPIModel):
    id: str
    status: str
    league: LeaguePublic
    policy_version: PolicyVersionPublic
    player: PlayerPublic | None = None
    league_policy_membership_id: str | None = None
    notes: str | None = None
    created_at: datetime


class RoundPublic(CoworldAPIModel):
    id: str
    round_number: int
    commissioner_key: str
    execution_backend: str
    round_config: dict[str, Any]
    round_display: dict[str, Any] | None = None
    status: str
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    division: DivisionPublic
    created_at: datetime


class RoundListPublic(CoworldAPIModel):
    entries: list[RoundPublic]
    total_count: int
    limit: int
    offset: int


class EnvConfigPublic(CoworldAPIModel):
    id: UUID
    name: str | None = None
    compat_version: str | None = None
    num_agents: int | None = None
    created_at: datetime


class PolicyPoolPublic(CoworldAPIModel):
    id: str
    round_id: str | None = None
    pool_index: int | None = None
    label: str
    pool_type: str
    env_config: EnvConfigPublic | None = None
    coworld_id: str | None = None
    config: dict[str, Any]
    status: str
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime


class PolicyPoolEntryPublic(CoworldAPIModel):
    id: UUID
    pool_id: str
    league_policy_membership_id: str | None = None
    policy_version: PolicyVersionPublic
    player: PlayerPublic | None = None
    seed_order: int
    metadata: dict[str, Any] | None = None
    created_at: datetime


class PoolDetailPublic(PolicyPoolPublic):
    entries: list[PolicyPoolEntryPublic]


class RoundResultPublic(CoworldAPIModel):
    id: str
    rank: int
    score: float
    result_metadata: dict[str, Any] | None = None
    policy_version: PolicyVersionPublic
    player: PlayerPublic | None = None
    created_at: datetime


class RoundDetailPublic(RoundPublic):
    pools: list[PolicyPoolPublic]
    results: list[RoundResultPublic]


class LeaderboardRecentRoundPublic(CoworldAPIModel):
    id: str
    round_number: int
    status: str
    rank: int | None = None
    score: float | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class LeaderboardEntryPublic(CoworldAPIModel):
    player_id: str
    player_name: str | None = None
    avg_score: float
    rounds_played: int
    recent_rounds: list[LeaderboardRecentRoundPublic] | None = None


class V2EpisodeRequestParticipant(CoworldAPIModel):
    position: int
    policy_version_id: UUID
    policy_id: UUID
    policy_name: str
    version: int
    player_id: str | None = None
    player_name: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def label(self) -> str:
        return f"{self.policy_name}:v{self.version}"


class EpisodeRequestScore(CoworldAPIModel):
    policy_version_id: UUID
    score: float


class V2EpisodeRequestRow(CoworldAPIModel):
    id: str
    requester_user_id: str
    pool_id: str | None = None
    mod_name: str | None = None
    env_config_name: str | None = None
    coworld_id: str | None = None
    seed: int | None = None
    assignments: list[int]
    max_steps: int | None = None
    status: str
    policy_version_ids: list[UUID]
    participants: list[V2EpisodeRequestParticipant]
    job_id: UUID | None = None
    episode_id: UUID | None = None
    replay_url: str | None = None
    scores: list[EpisodeRequestScore]
    created_at: datetime


class CompetitionEventPublic(CoworldAPIModel):
    id: str
    event_type: str
    audience: str
    user_id: str | None = None
    player: PlayerPublic | None = None
    policy_version: PolicyVersionPublic | None = None
    league: LeaguePublic | None = None
    division: DivisionPublic | None = None
    round_id: str | None = None
    headline: str
    summary: str
    payload: dict[str, Any]
    created_at: datetime


class AgentStatsDetail(CoworldAPIModel):
    agent_id: int
    reward: float
    metrics: dict[str, float]


class PolicyStatsDetail(CoworldAPIModel):
    position: int
    policy_version_id: UUID | None = None
    policy_name: str | None = None
    policy_version: int | None = None
    num_agents: int
    avg_metrics: dict[str, float]
    avg_reward: float
    agents: list[AgentStatsDetail]


class EpisodeStatsResponse(CoworldAPIModel):
    game_stats: dict[str, float]
    policy_stats: list[PolicyStatsDetail]
    steps: int | None = None


class CoworldReplaySessionResponse(CoworldAPIModel):
    viewer_url: str


class PolicyVersionRow(CoworldAPIModel):
    id: UUID | None = None
    policy_version_id: UUID | None = None
    name: str | None = None
    policy_name: str | None = None
    version: int

    @property
    def resolved_id(self) -> UUID:
        resolved = self.id or self.policy_version_id
        assert resolved is not None, "policy version row is missing an id"
        return resolved

    @property
    def resolved_name(self) -> str:
        resolved = self.name or self.policy_name
        assert resolved is not None, "policy version row is missing a name"
        return resolved


class PolicyVersionsResponse(CoworldAPIModel):
    entries: list[PolicyVersionRow]
    total_count: int


class CoworldApiClient:
    def __init__(self, *, server_url: str, token: str | None = None):
        self._http_client = httpx.Client(base_url=server_url, timeout=30.0, follow_redirects=True)
        self._token = token

    @classmethod
    def from_login(cls, *, server_url: str) -> Self:
        token = _load_current_cogames_token()
        if token is None:
            raise RuntimeError("Not authenticated. Run: uv run softmax login")
        return cls(server_url=server_url, token=token)

    def close(self) -> None:
        self._http_client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        self.close()

    def _headers(self) -> dict[str, str]:
        if self._token is None:
            return {}
        return {"X-Auth-Token": self._token}

    def _request(self, method: str, path: str, response_type: type[Any], **kwargs: Any) -> Any:
        response = self._http_client.request(method, path, headers=self._headers(), **kwargs)
        response.raise_for_status()
        return TypeAdapter(response_type).validate_python(response.json())

    def _get(self, path: str, response_type: type[Any], **kwargs: Any) -> Any:
        return self._request("GET", path, response_type, **kwargs)

    def _post(self, path: str, response_type: type[Any], **kwargs: Any) -> Any:
        return self._request("POST", path, response_type, **kwargs)

    def get_bytes(self, path: str) -> bytes:
        response = self._http_client.get(path, headers=self._headers())
        response.raise_for_status()
        return response.content

    def get_text(self, path: str) -> str:
        response = self._http_client.get(path, headers=self._headers())
        response.raise_for_status()
        return response.text

    def list_games(self) -> list[GamePublic]:
        return self._get("/v2/games", list[GamePublic])

    def list_leagues(self, *, game_id: str | None = None) -> list[LeaguePublic]:
        params = {"game_id": game_id} if game_id is not None else None
        return self._get("/v2/leagues", list[LeaguePublic], params=params)

    def get_league(self, league_id: str) -> LeaguePublic:
        return self._get(f"/v2/leagues/{league_id}", LeaguePublic)

    def get_league_division_ladder(self, league_id: str) -> list[DivisionLadderEntryPublic]:
        return self._get(f"/v2/leagues/{league_id}/division-ladder", list[DivisionLadderEntryPublic])

    def list_divisions(self, *, league_id: str | None = None) -> list[DivisionPublic]:
        params = {"league_id": league_id} if league_id is not None else None
        return self._get("/v2/divisions", list[DivisionPublic], params=params)

    def get_division(self, division_id: str) -> DivisionPublic:
        return self._get(f"/v2/divisions/{division_id}", DivisionPublic)

    def get_division_leaderboard(
        self,
        division_id: str,
        *,
        include_recent_rounds: int = 0,
    ) -> list[LeaderboardEntryPublic]:
        return self._get(
            f"/v2/divisions/{division_id}/leaderboard",
            list[LeaderboardEntryPublic],
            params={"include_recent_rounds": include_recent_rounds},
        )

    def list_rounds(
        self,
        *,
        league_id: str | None = None,
        division_id: str | None = None,
        status: str | None = None,
        limit: int = 25,
        offset: int = 0,
    ) -> RoundListPublic:
        params: dict[str, str | int] = {"limit": limit, "offset": offset}
        if league_id is not None:
            params["league_id"] = league_id
        if division_id is not None:
            params["division_id"] = division_id
        if status is not None:
            params["status"] = status
        return self._get("/v2/rounds", RoundListPublic, params=params)

    def get_round(self, round_id: str) -> RoundDetailPublic:
        return self._get(f"/v2/rounds/{round_id}", RoundDetailPublic)

    def list_pools(
        self,
        *,
        round_id: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[PolicyPoolPublic]:
        params: dict[str, str | int] = {"limit": limit, "offset": offset}
        if round_id is not None:
            params["round_id"] = round_id
        return self._get("/v2/pools", list[PolicyPoolPublic], params=params)

    def get_pool(self, pool_id: str) -> PoolDetailPublic:
        return self._get(f"/v2/pools/{pool_id}", PoolDetailPublic)

    def list_memberships(
        self,
        *,
        league_id: str | None = None,
        division_id: str | None = None,
        policy_version_id: UUID | None = None,
        player_id: str | None = None,
        active_only: bool = False,
        champions_only: bool = False,
        mine: bool = False,
        limit: int | None = None,
    ) -> list[LeaguePolicyMembershipPublic]:
        params: dict[str, str | int | bool] = {
            "active_only": str(active_only).lower(),
            "champions_only": str(champions_only).lower(),
            "mine": str(mine).lower(),
        }
        if league_id is not None:
            params["league_id"] = league_id
        if division_id is not None:
            params["division_id"] = division_id
        if policy_version_id is not None:
            params["policy_version_id"] = str(policy_version_id)
        if player_id is not None:
            params["player_id"] = player_id
        if limit is not None:
            params["limit"] = limit
        return self._get("/v2/league-policy-memberships", list[LeaguePolicyMembershipPublic], params=params)

    def list_submissions(
        self,
        *,
        league_id: str | None = None,
        player_id: str | None = None,
        policy_version_id: UUID | None = None,
        mine: bool = False,
        limit: int | None = None,
    ) -> list[LeagueSubmissionPublic]:
        params: dict[str, str | int | bool] = {"mine": str(mine).lower()}
        if league_id is not None:
            params["league_id"] = league_id
        if player_id is not None:
            params["player_id"] = player_id
        if policy_version_id is not None:
            params["policy_version_id"] = str(policy_version_id)
        if limit is not None:
            params["limit"] = limit
        return self._get("/v2/league-submissions", list[LeagueSubmissionPublic], params=params)

    def list_episode_requests(
        self,
        *,
        pool_id: str | None = None,
        player_id: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[V2EpisodeRequestRow]:
        params: dict[str, str | int] = {"limit": limit, "offset": offset}
        if pool_id is not None:
            params["pool_id"] = pool_id
        if player_id is not None:
            params["player_id"] = player_id
        return self._get("/v2/episode-requests", list[V2EpisodeRequestRow], params=params)

    def get_episode_request(self, episode_request_id: str) -> V2EpisodeRequestRow:
        return self._get(f"/v2/episode-requests/{episode_request_id}", V2EpisodeRequestRow)

    def list_events(
        self,
        *,
        league_id: str | None = None,
        division_id: str | None = None,
        round_id: str | None = None,
        event_type: str | None = None,
        audience: str | None = None,
        player_id: str | None = None,
        policy_version_id: UUID | None = None,
        limit: int = 50,
    ) -> list[CompetitionEventPublic]:
        params: dict[str, str | int] = {"limit": limit}
        if league_id is not None:
            params["league_id"] = league_id
        if division_id is not None:
            params["division_id"] = division_id
        if round_id is not None:
            params["round_id"] = round_id
        if event_type is not None:
            params["event_type"] = event_type
        if audience is not None:
            params["audience"] = audience
        if player_id is not None:
            params["player_id"] = player_id
        if policy_version_id is not None:
            params["policy_version_id"] = str(policy_version_id)
        return self._get("/v2/competition-events", list[CompetitionEventPublic], params=params)

    def get_job_episode_stats(self, job_id: UUID) -> EpisodeStatsResponse:
        return self._get(f"/jobs/{job_id}/episode-stats", EpisodeStatsResponse)

    def get_job_artifact_bytes(self, job_id: UUID, artifact_type: str) -> bytes:
        return self.get_bytes(f"/jobs/{job_id}/artifacts/{artifact_type}")

    def get_job_artifact_text(self, job_id: UUID, artifact_type: str) -> str:
        return self.get_text(f"/jobs/{job_id}/artifacts/{artifact_type}")

    def list_job_policy_logs(self, job_id: UUID) -> list[str]:
        return self._get(f"/jobs/{job_id}/policy-logs", list[str])

    def get_job_policy_log(self, job_id: UUID, agent_idx: int) -> str:
        return self.get_text(f"/jobs/{job_id}/policy-logs/{agent_idx}")

    def create_replay_session(self, *, coworld_id: str, replay_uri: str) -> CoworldReplaySessionResponse:
        return self._post(
            "/v2/coworlds/replays/session",
            CoworldReplaySessionResponse,
            json={"coworld_id": coworld_id, "replay_uri": replay_uri},
        )

    def lookup_policy_version(self, *, name: str, version: int | None = None) -> PolicyVersionRow | None:
        params: dict[str, str | int] = {"mine": "true", "name_exact": name, "limit": 100}
        if version is not None:
            params["version"] = version
        response = self._get("/stats/policy-versions", PolicyVersionsResponse, params=params)
        return response.entries[0] if response.entries else None


def _load_current_cogames_token() -> str | None:
    from softmax.auth import get_login_server, load_current_cogames_token  # noqa: PLC0415

    return load_current_cogames_token(login_server=get_login_server())
