from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any, Literal, Self
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, computed_field


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
    commissioner_config: dict[str, Any] | None = None
    public: bool = False
    hidden: bool = False
    is_game_of_week: bool = False
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
    archived_at: datetime | None = None
    commissioner_description: DivisionCommissionerDescriptionPublic | None = None
    created_at: datetime


class DivisionLadderEntryPublic(CoworldAPIModel):
    id: str
    name: str
    level: int
    member_count: int


class LeaguePolicyMembershipPublic(CoworldAPIModel):
    id: str
    status: str
    substatus: str | None = None
    is_champion: bool = False
    # OpenAPI marks start_time optional (the SQLModel base sets default_factory),
    # so mirror that here. The DB column is non-null, so reads always carry a value.
    start_time: datetime | None = None
    end_time: datetime | None = None
    league: LeaguePublic
    division: DivisionPublic
    policy_version: PolicyVersionPublic
    player: PlayerPublic | None = None
    created_at: datetime


class LeagueSubmissionPublic(CoworldAPIModel):
    id: str
    auto_champion: str = "always"
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
    num_agents: int | None = None
    created_at: datetime


class RoundResultPublic(CoworldAPIModel):
    id: str
    rank: int
    score: float
    result_metadata: dict[str, Any] | None = None
    policy_version: PolicyVersionPublic
    player: PlayerPublic | None = None
    created_at: datetime


class RoundDetailPublic(RoundPublic):
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
    rank: int | None = None
    player_id: str
    player_name: str | None = None
    score: float
    rounds_played: int
    recent_rounds: list[LeaderboardRecentRoundPublic] | None = None


LeaderboardValuePublic = str | int | float | bool | None


class LeaderboardAxisPublic(CoworldAPIModel):
    key: str
    label: str | None = None


class LeaderboardColumnPublic(CoworldAPIModel):
    key: str
    label: str | None = None
    value_type: Literal["number", "integer", "string", "boolean"] = "number"
    sort: Literal["asc", "desc"] | None = None


class LeaderboardRowPublic(CoworldAPIModel):
    subject_type: str = "player"
    subject_id: str
    subject_name: str | None = None
    values: dict[str, LeaderboardValuePublic]
    policy_version_ids: set[UUID] = Field(default_factory=set)
    recent_rounds: list[LeaderboardRecentRoundPublic] | None = None


class LeaderboardViewPublic(CoworldAPIModel):
    key: str
    title: str | None = None
    description: str | None = None
    axis_values: dict[str, str]
    columns: list[LeaderboardColumnPublic]
    rows: list[LeaderboardRowPublic]


class DivisionLeaderboardsPublic(CoworldAPIModel):
    default_view_key: str
    axes: list[LeaderboardAxisPublic]
    views: list[LeaderboardViewPublic]


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
    round_id: str | None = None
    mod_name: str | None = None
    env_config_name: str | None = None
    coworld_id: str | None = None
    game_config: dict[str, Any] | None = None
    seed: int | None = None
    max_steps: int | None = None
    status: str
    policy_version_ids: list[UUID]
    participants: list[V2EpisodeRequestParticipant]
    job_id: UUID | None = None
    episode_id: UUID | None = None
    replay_url: str | None = None
    live_url: str | None = None
    error_type: str | None = None
    error: str | None = None
    failed_policy_index: int | None = None
    failed_agent_index: int | None = None
    scores: list[EpisodeRequestScore]
    created_at: datetime


class ExperienceRequestRow(CoworldAPIModel):
    id: str
    requester_user_id: str
    requester: str | None = None
    coworld_id: str
    coworld_name: str
    coworld_version: str
    variant_id: str | None = None
    status: str
    episode_count: int
    pending_count: int
    submitted_count: int
    running_count: int
    completed_count: int
    failed_count: int
    error: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


class ExperienceRequestDetail(ExperienceRequestRow):
    episodes: list[V2EpisodeRequestRow]


class ExperienceRequestPage(CoworldAPIModel):
    entries: list[ExperienceRequestRow]
    total_count: int
    limit: int
    offset: int


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


class EpisodeRequestPolicyArtifactInfo(CoworldAPIModel):
    position: int
    policy_version_id: UUID
    policy_name: str | None = None
    has_log: bool
    has_artifact: bool


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
    # Process-scoped: set by the top-level Typer `--elevated` callback in `coworld/cli.py`
    # so it applies to every client constructed later in the same invocation. Client-side
    # code that instantiates the client outside the CLI can flip this too, but the flag is
    # only ever sent on user-owned tokens (see _headers() — player-subject tokens are
    # refused because their elevation would be a no-op at the backend anyway).
    _elevated = False

    def __init__(self, *, server_url: str, token: str | None = None):
        root = server_url.rstrip("/")
        base_url = f"{root}/observatory"
        self._http_client = httpx.Client(base_url=base_url, timeout=30.0, follow_redirects=True)
        self._token = token

    @classmethod
    def set_elevated(cls, elevated: bool) -> None:
        cls._elevated = elevated

    @classmethod
    def from_login(cls, *, server_url: str) -> Self:
        token = _load_current_token(server_url=server_url)
        if token is None:
            raise RuntimeError(f"Not authenticated. Run: uv run softmax login --server {server_url}")
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
        headers = {"Authorization": f"Bearer {self._token}"}
        if type(self)._elevated:
            if self._token.startswith("ply_"):
                raise RuntimeError(
                    "--elevated cannot be used with a player-subject token. Player sessions "
                    "are not eligible for Softmax team access. Run `softmax player unset` to "
                    "revert to your user credential, or omit --elevated."
                )
            headers["X-Use-Elevated-Privileges"] = "true"
        return headers

    def _request(self, method: str, path: str, response_type: Any, **kwargs: Any) -> Any:
        response = self._http_client.request(method, path, headers=self._headers(), **kwargs)
        _raise_for_status(response)
        return TypeAdapter(response_type).validate_python(response.json())

    def _get(self, path: str, response_type: Any, **kwargs: Any) -> Any:
        return self._request("GET", path, response_type, **kwargs)

    def _post(self, path: str, response_type: Any, **kwargs: Any) -> Any:
        return self._request("POST", path, response_type, **kwargs)

    def get_bytes(self, path: str, *, timeout: float | None = None) -> bytes:
        response = self._http_client.get(path, headers=self._headers(), timeout=timeout)
        _raise_for_status(response)
        return response.content

    def get_text(self, path: str, *, timeout: float | None = None) -> str:
        response = self._http_client.get(path, headers=self._headers(), timeout=timeout)
        _raise_for_status(response)
        return response.text

    def list_games(self) -> list[GamePublic]:
        return self._get("/v2/games", list[GamePublic])

    def list_leagues(self, *, game_id: str | None = None) -> list[LeaguePublic]:
        params = {"game_id": game_id} if game_id is not None else None
        return self._get("/v2/leagues", list[LeaguePublic], params=params)

    def get_league(self, league_id: str) -> LeaguePublic:
        return self._get(f"/v2/leagues/{league_id}", LeaguePublic)

    def get_game_of_week_league(self) -> LeaguePublic | None:
        return self._get("/v2/leagues/game-of-week", LeaguePublic | None)

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
        # The endpoint returns JSON null for divisions with an empty leaderboard; coalesce to [].
        rows = self._get(
            f"/v2/divisions/{division_id}/leaderboard",
            list[LeaderboardEntryPublic] | None,
            params={"include_recent_rounds": include_recent_rounds},
        )
        return rows or []

    def get_division_leaderboards(
        self,
        division_id: str,
        *,
        include_recent_rounds: int = 0,
    ) -> DivisionLeaderboardsPublic | None:
        return self._get(
            f"/v2/divisions/{division_id}/leaderboards",
            DivisionLeaderboardsPublic | None,
            params={"include_recent_rounds": include_recent_rounds},
        )

    def get_division_leaderboard_tables(
        self,
        division_id: str,
        *,
        include_recent_rounds: int = 0,
    ) -> DivisionLeaderboardsPublic | None:
        # TODO: delete compatibility shim after callers stop using table terminology.
        return self.get_division_leaderboards(
            division_id,
            include_recent_rounds=include_recent_rounds,
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

    def retire_membership(
        self,
        membership_id: str,
        *,
        reason: str | None = None,
    ) -> LeaguePolicyMembershipPublic:
        kwargs: dict[str, Any] = {}
        if reason is not None:
            kwargs["json"] = {"reason": reason}
        return self._post(
            f"/v2/league-policy-memberships/{membership_id}/retire",
            LeaguePolicyMembershipPublic,
            **kwargs,
        )

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
        division_id: str | None = None,
        round_id: str | None = None,
        player_id: str | None = None,
        policy_version_id: UUID | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[V2EpisodeRequestRow]:
        params: dict[str, str | int] = {"limit": limit, "offset": offset}
        if division_id is not None:
            params["division_id"] = division_id
        if round_id is not None:
            params["round_id"] = round_id
        if player_id is not None:
            params["player_id"] = player_id
        if policy_version_id is not None:
            params["policy_version_id"] = str(policy_version_id)
        response = self._http_client.get("/v2/episode-requests", headers=self._headers(), params=params)
        _raise_for_status(response)
        page = response.json()
        return TypeAdapter(list[V2EpisodeRequestRow]).validate_python(page["entries"])

    def get_episode_request(self, episode_request_id: str) -> V2EpisodeRequestRow:
        return self._get(f"/v2/episode-requests/{episode_request_id}", V2EpisodeRequestRow)

    def get_episode_request_artifact_text(self, episode_request_id: str, artifact_type: str) -> str:
        return self.get_text(f"/v2/episode-requests/{episode_request_id}/artifacts/{artifact_type}")

    def get_episode_request_bundle(self, episode_request_id: str, include: Iterable[str] | None = None) -> bytes:
        params = None if include is None else {"include": ",".join(include)}
        response = self._http_client.get(
            f"/v2/episode-requests/{episode_request_id}/bundle",
            headers=self._headers(),
            params=params,
        )
        _raise_for_status(response)
        return response.content

    def create_experience_request(self, body: dict[str, Any]) -> ExperienceRequestDetail:
        return self._post("/v2/experience-requests", ExperienceRequestDetail, json=body, timeout=120.0)

    def list_experience_requests(
        self,
        *,
        mine: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> ExperienceRequestPage:
        return self._get(
            "/v2/experience-requests",
            ExperienceRequestPage,
            params={"mine": str(mine).lower(), "limit": limit, "offset": offset},
        )

    def get_experience_request(self, experience_request_id: str) -> ExperienceRequestDetail:
        return self._get(f"/v2/experience-requests/{experience_request_id}", ExperienceRequestDetail)

    def list_experience_request_episodes(self, experience_request_id: str) -> list[V2EpisodeRequestRow]:
        return self._get(
            f"/v2/experience-requests/{experience_request_id}/episodes",
            list[V2EpisodeRequestRow],
        )

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

    def get_job_artifact_bytes(self, job_id: UUID, artifact_type: str) -> bytes:
        return self.get_bytes(f"/jobs/{job_id}/artifacts/{artifact_type}")

    def get_episode_request_episode_stats(self, episode_request_id: str) -> EpisodeStatsResponse:
        return self._get(f"/v2/episode-requests/{episode_request_id}/episode-stats", EpisodeStatsResponse)

    def get_episode_request_artifact_bytes(self, episode_request_id: str, artifact_type: str) -> bytes:
        return self.get_bytes(f"/v2/episode-requests/{episode_request_id}/artifacts/{artifact_type}")

    def list_episode_request_policy_artifacts(self, episode_request_id: str) -> list[EpisodeRequestPolicyArtifactInfo]:
        return self._get(
            f"/v2/episode-requests/{episode_request_id}/policy-artifacts",
            list[EpisodeRequestPolicyArtifactInfo],
        )

    def get_episode_request_policy_log(self, episode_request_id: str, policy_version_id: UUID, agent_idx: int) -> str:
        return self.get_text(f"/v2/episode-requests/{episode_request_id}/{policy_version_id}/policy-logs/{agent_idx}")

    def get_episode_request_policy_artifact(
        self, episode_request_id: str, policy_version_id: UUID, agent_idx: int
    ) -> bytes:
        return self.get_bytes(
            f"/v2/episode-requests/{episode_request_id}/{policy_version_id}/policy-artifact/{agent_idx}"
        )

    def create_replay_session(
        self, *, coworld_id: str, episode_id: UUID, replay_uri: str
    ) -> CoworldReplaySessionResponse:
        return self._post(
            "/v2/coworlds/replays/session",
            CoworldReplaySessionResponse,
            json={"coworld_id": coworld_id, "episode_id": str(episode_id), "replay_uri": replay_uri},
        )

    def lookup_policy_version(self, *, name: str, version: int | None = None) -> PolicyVersionRow | None:
        params: dict[str, str | int] = {"mine": "true", "name_exact": name, "limit": 100}
        if version is not None:
            params["version"] = version
        response = self._get("/stats/policy-versions", PolicyVersionsResponse, params=params)
        return response.entries[0] if response.entries else None


def _raise_for_status(response: httpx.Response) -> None:
    if response.status_code == 401:
        raise RuntimeError("Authentication failed (401). Your token may be expired. Run: uv run softmax login")
    if response.status_code == 403:
        raise RuntimeError(
            f"Access denied (403) for {response.request.url.path}. "
            "You may lack permissions, or your token may be expired. Run: uv run softmax login"
        )
    response.raise_for_status()


def _load_current_token(*, server_url: str) -> str | None:
    from softmax.auth import load_current_token  # noqa: PLC0415

    return load_current_token(server=server_url)
