from __future__ import annotations

import json
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

_STATE_MAX_BYTES = 10 * 1024 * 1024
POLICY_MEMBERSHIP_STATUS_COMPETING = "competing"
POLICY_MEMBERSHIP_SUBSTATUS_ACTIVE = "active"
POLICY_MEMBERSHIP_SUBSTATUS_BENCHED = "benched"


class LeagueInfo(BaseModel):
    id: UUID
    commissioner_key: str | None = None
    commissioner_config: dict[str, Any] | None = None


class DivisionInfo(BaseModel):
    id: UUID
    name: str
    level: int
    type: str = "competition"


class DivisionConfig(BaseModel):
    name: str
    level: int
    type: str = "competition"
    description: str | None = None
    previous_name: str | None = None


class MembershipInfo(BaseModel):
    id: UUID
    league_id: UUID
    division_id: UUID
    policy_version_id: UUID
    player_id: str | None = None
    status: str = "competing"
    substatus: str | None = None
    is_champion: bool = False


class RecentResult(BaseModel):
    round_id: UUID
    division_id: UUID
    round_number: int
    policy_version_id: UUID
    rank: int
    score: float
    player_id: str | None = None
    player_name: str | None = None
    result_metadata: dict[str, Any] = Field(default_factory=dict)
    completed_at: str | None = None


class VariantInfo(BaseModel):
    id: str
    name: str
    game_config: dict[str, Any]
    # TODO(commissioner-rollout): remove this deprecated wire-compat field with
    # `_compat_variant_num_agents` after deployed commissioner containers accept
    # roster-owned episode player counts. Track every cleanup site with this tag.
    num_agents: int = Field(default=1, gt=0)


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
    scores: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def include_primary_score(self) -> "EpisodeScore":
        if "score" not in self.scores:
            self.scores = {"score": self.score, **self.scores}
        return self


class RankingEntry(BaseModel):
    policy_version_id: UUID
    player_id: str | None = None
    rank: int
    score: float
    result_metadata: dict[str, Any] = Field(default_factory=dict)


class DivisionRanking(BaseModel):
    division_id: UUID
    rankings: list[RankingEntry]


class MembershipChange(BaseModel):
    membership_id: UUID
    from_division_id: UUID
    to_division_id: UUID | None = None
    is_active: bool = True
    reason: str


class PolicyMembershipEventEvidence(BaseModel):
    type: str
    public_id: str | None = None
    title: str
    summary: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PolicyMembershipEventChange(BaseModel):
    league_policy_membership_id: UUID
    from_division_id: UUID | None = None
    to_division_id: UUID | None = None
    status: str
    substatus: str | None = None
    reason: str
    end_time: str | None = None
    notes: str | None = None
    evidence: list[PolicyMembershipEventEvidence] = Field(default_factory=list)


class StageConfig(BaseModel):
    label: str = "Round"
    num_episodes: int = Field(default=1, gt=0)
    min_episodes_per_entrant: int | None = Field(default=None, gt=0)
    self_play: bool = False


class RoundConfig(BaseModel):
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
    execution_backend: str = "dispatch"
    notes: str | None = None


class DivisionLeaderboardEntry(BaseModel):
    player_id: str
    player_name: str | None = None
    rank: int
    score: float
    rounds_played: int
    policy_version_ids: set[UUID] = Field(default_factory=set)
    recent_rounds: list[dict[str, Any]] | None = None
    # All-time episode win/played totals carried through the rank_division wire path so the
    # scheduling-tick board (synthesized below by `_row_from_entry`) surfaces the same Competition
    # Win %/EPISODES columns as the round-complete board, instead of clobbering it with a 3-column
    # view. `episode_wins`/`episodes_played` are the Win % numerator/denominator; `win_rate` is the
    # clamped ratio (commissioners may send it directly, else it is derived from the totals). All
    # default to None for backward compatibility / non-competition divisions that omit them.
    episode_wins: float | None = None
    episodes_played: int | None = None
    win_rate: float | None = None


LeaderboardValue = str | int | float | bool | None


class DivisionLeaderboardAxis(BaseModel):
    key: str
    label: str | None = None


class DivisionLeaderboardColumn(BaseModel):
    key: str
    label: str | None = None
    value_type: Literal["number", "integer", "string", "boolean"] = "number"
    sort: Literal["asc", "desc"] | None = None


class DivisionLeaderboardRow(BaseModel):
    subject_type: str = "player"
    subject_id: str
    subject_name: str | None = None
    values: dict[str, LeaderboardValue] = Field(default_factory=dict)
    policy_version_ids: set[UUID] = Field(default_factory=set)
    recent_rounds: list[dict[str, Any]] | None = None


class DivisionLeaderboardView(BaseModel):
    key: str = "score"
    title: str | None = None
    description: str | None = None
    axis_values: dict[str, str] = Field(default_factory=dict)
    columns: list[DivisionLeaderboardColumn] = Field(default_factory=list)
    rows: list[DivisionLeaderboardRow] = Field(default_factory=list)


class DivisionLeaderboard(BaseModel):
    division_id: UUID
    default_view_key: str = "score"
    axes: list[DivisionLeaderboardAxis] = Field(default_factory=list)
    views: list[DivisionLeaderboardView] = Field(default_factory=list)


class DivisionLeaderboardTable(BaseModel):
    # TODO: delete compatibility model after all commissioners publish DivisionLeaderboardView.
    # Stable table identifier used by primary_table_id and clients; usually the metric key.
    id: str = "score"
    # Human-facing table/tab title, e.g. "Winrate 24h".
    label: str = "Score"
    description: str | None = None
    # Human-facing label for entry.score in this table, e.g. "Winrate".
    score_label: str = "Score"
    rankings: list[DivisionLeaderboardEntry] = Field(default_factory=list)


def _legacy_score_column_key(view: DivisionLeaderboardView) -> str:
    # Prefer an explicit "score" column when present: a competition board also carries a "win_rate"
    # column with sort="desc" that precedes "score", and the heuristic below would otherwise pick
    # win_rate as the legacy score (collapsing Score onto the Win % rate). Mirrors the backend's
    # `commissioners._legacy_score_column_key`.
    if any(column.key == "score" for column in view.columns):
        return "score"
    for column in view.columns:
        if column.key != "rank" and column.sort == "desc" and column.value_type in {"number", "integer"}:
            return column.key
    for column in view.columns:
        if column.key != "rank" and column.value_type in {"number", "integer"}:
            return column.key
    return "score"


def _entry_from_row(row: DivisionLeaderboardRow, rank: int, score_axis_key: str) -> DivisionLeaderboardEntry:
    score = row.values.get(score_axis_key)
    row_rank = row.values.get("rank", rank)
    rounds_played = row.values.get("rounds_played", 0)
    episode_wins = row.values.get("episode_wins", row.values.get("wins"))
    episodes_played = row.values.get("episodes_played")
    win_rate = row.values.get("win_rate")

    def _as_float(value: LeaderboardValue) -> float | None:
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None

    def _as_int(value: LeaderboardValue) -> int | None:
        return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None

    return DivisionLeaderboardEntry(
        player_id=row.subject_id,
        player_name=row.subject_name,
        rank=int(row_rank) if isinstance(row_rank, (int, float)) else rank,
        score=float(score) if isinstance(score, (int, float)) else 0.0,
        rounds_played=int(rounds_played) if isinstance(rounds_played, (int, float)) else 0,
        policy_version_ids=row.policy_version_ids,
        recent_rounds=row.recent_rounds,
        episode_wins=_as_float(episode_wins),
        episodes_played=_as_int(episodes_played),
        win_rate=_as_float(win_rate),
    )


def _entry_has_episode_metrics(entry: DivisionLeaderboardEntry) -> bool:
    return entry.episodes_played is not None or entry.episode_wins is not None or entry.win_rate is not None


def _entry_win_rate(entry: DivisionLeaderboardEntry) -> float | None:
    """Clamped Competition Win % for the entry.

    Prefer the commissioner-provided ``win_rate`` when present; otherwise derive it from the
    all-time episode totals (``episode_wins / episodes_played``) and clamp to ``[0, 1]`` to mirror
    the commissioner's ``_clamped_win_rate``. Returns None when the entry carries no episode metrics
    (older / non-competition entries) so the synthesized view stays 3-column.
    """
    if entry.win_rate is not None:
        return entry.win_rate
    if entry.episodes_played is None or entry.episode_wins is None:
        return None
    if entry.episodes_played <= 0:
        return 0.0
    return max(0.0, min(1.0, entry.episode_wins / entry.episodes_played))


def _row_from_entry(entry: DivisionLeaderboardEntry) -> DivisionLeaderboardRow:
    values: dict[str, LeaderboardValue] = {
        "rank": entry.rank,
        "score": entry.score,
        "rounds_played": entry.rounds_played,
    }
    # Carry the Competition Win %/EPISODES metrics into the synthesized row WHEN PRESENT so the
    # scheduling-tick board matches the round-complete board's column/value shape (and the read path
    # `legacy_entries` picks them up from `win_rate`/`wins`/`episodes_played`). When the entry omits
    # them (non-competition / older commissioners) the row stays the legacy 3 values.
    if _entry_has_episode_metrics(entry):
        win_rate = _entry_win_rate(entry)
        if win_rate is not None:
            values["win_rate"] = win_rate
        if entry.episode_wins is not None:
            # `wins` is the read-path key; `episode_wins` mirrors the round-complete board verbatim.
            values["wins"] = entry.episode_wins
            values["episode_wins"] = entry.episode_wins
        if entry.episodes_played is not None:
            values["episodes_played"] = entry.episodes_played
    return DivisionLeaderboardRow(
        subject_type="player",
        subject_id=entry.player_id,
        subject_name=entry.player_name,
        values=values,
        policy_version_ids=entry.policy_version_ids,
        recent_rounds=entry.recent_rounds,
    )


def _columns_for_entries(entries: list[DivisionLeaderboardEntry]) -> list[DivisionLeaderboardColumn]:
    """Column set for a synthesized `rankings` view.

    Competition entries (those carrying episode metrics) get the full Win %/EPISODES layout that
    matches the round-complete board so the two writers persist identical board shapes; everything
    else keeps the legacy 3-column board so nothing regresses.
    """
    columns = [
        DivisionLeaderboardColumn(key="rank", label="Rank", value_type="integer", sort="asc"),
        DivisionLeaderboardColumn(key="score", label="Score", value_type="number", sort="desc"),
        DivisionLeaderboardColumn(key="rounds_played", label="Rounds Played", value_type="integer"),
    ]
    if not any(_entry_has_episode_metrics(entry) for entry in entries):
        return columns
    return [
        DivisionLeaderboardColumn(key="rank", label="Rank", value_type="integer", sort="asc"),
        DivisionLeaderboardColumn(key="win_rate", label="Win %", value_type="number", sort="desc"),
        DivisionLeaderboardColumn(key="score", label="Score", value_type="number", sort="desc"),
        DivisionLeaderboardColumn(key="wins", label="Wins", value_type="number"),
        DivisionLeaderboardColumn(key="episodes_played", label="Episodes Played", value_type="integer"),
        DivisionLeaderboardColumn(key="rounds_played", label="Rounds Played", value_type="integer"),
        DivisionLeaderboardColumn(key="episode_wins", label="Episode Wins", value_type="number"),
    ]


def _row_from_ranking_entry(entry: RankingEntry) -> DivisionLeaderboardRow:
    subject_type = "player" if entry.player_id else "policy_version"
    subject_id = entry.player_id or str(entry.policy_version_id)
    return DivisionLeaderboardRow(
        subject_type=subject_type,
        subject_id=subject_id,
        values={"rank": entry.rank, "score": entry.score},
        policy_version_ids={entry.policy_version_id},
    )


def _axis_defs_from_views(views: list[DivisionLeaderboardView]) -> list[DivisionLeaderboardAxis]:
    axis_keys: list[str] = []
    for view in views:
        for key in view.axis_values:
            if key not in axis_keys:
                axis_keys.append(key)
    return [DivisionLeaderboardAxis(key=key, label=key.replace("_", " ").title()) for key in axis_keys]


def _leaderboard_from_division_ranking(result: DivisionRanking) -> DivisionLeaderboard:
    # TODO: delete compatibility shim after commissioners publish RoundComplete.leaderboards directly.
    view = DivisionLeaderboardView(
        key="score",
        title="Score",
        axis_values={"metric": "score", "timeframe": "legacy"},
        columns=[
            DivisionLeaderboardColumn(key="rank", label="Rank", value_type="integer", sort="asc"),
            DivisionLeaderboardColumn(key="score", label="Score", value_type="number", sort="desc"),
        ],
        rows=[_row_from_ranking_entry(entry) for entry in result.rankings],
    )
    return DivisionLeaderboard(
        division_id=result.division_id,
        default_view_key=view.key,
        axes=_axis_defs_from_views([view]),
        views=[view],
    )


def _view_from_table(table: DivisionLeaderboardTable) -> DivisionLeaderboardView:
    # TODO: delete compatibility shim after table-shaped commissioner responses are gone.
    if any(_entry_has_episode_metrics(entry) for entry in table.rankings):
        columns = _columns_for_entries(table.rankings)
    else:
        columns = [
            DivisionLeaderboardColumn(key="rank", label="Rank", value_type="integer", sort="asc"),
            DivisionLeaderboardColumn(key="score", label=table.score_label, value_type="number", sort="desc"),
            DivisionLeaderboardColumn(key="rounds_played", label="Rounds Played", value_type="integer"),
        ]
    return DivisionLeaderboardView(
        key=table.id,
        title=table.label,
        description=table.description,
        columns=columns,
        rows=[_row_from_entry(entry) for entry in table.rankings],
    )


def _table_from_view(view: DivisionLeaderboardView) -> DivisionLeaderboardTable:
    # TODO: delete compatibility shim after callers stop reading table-shaped rank responses.
    score_column_key = _legacy_score_column_key(view)
    score_column = next((column for column in view.columns if column.key == score_column_key), None)
    return DivisionLeaderboardTable(
        id=view.key,
        label=view.title or view.key,
        description=view.description,
        score_label=(
            score_column.label if score_column is not None and score_column.label is not None else score_column_key
        ),
        rankings=[_entry_from_row(row, rank, score_column_key) for rank, row in enumerate(view.rows, start=1)],
    )


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


class EpisodeCancel(BaseModel):
    request_id: str
    reason: str

    def to_json(self) -> dict[str, Any]:
        data = self.model_dump(mode="json")
        data["type"] = "episode_cancel"
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


class CommissionerCalcStep(BaseModel):
    """One step in deriving an entrant's outcome: a human label + the value it produced.

    Steps read top-to-bottom as the arithmetic the commissioner performed
    (e.g. "imposter seats" -> [0, 1]; "kills on those seats" -> 4; "threshold" -> 0.5).
    ``inputs`` optionally records the raw per-seat / per-episode arrays the step
    consumed so a reader can fully reconstruct the calculation.
    """

    label: str
    value: Any = None
    inputs: dict[str, Any] = Field(default_factory=dict)
    # Optional: did this step's value clear its own gate/threshold (for pass/fail steps).
    passed: bool | None = None


class CommissionerEntrantReport(BaseModel):
    """How one entrant's round outcome was calculated, end to end.

    This is the *scoring trace* — inputs -> derivation -> output — that explains
    HOW a score was reached. It deliberately does NOT model the resulting
    placement move (promote/relegate/disqualify): that is already carried by
    ``policy_membership_events`` (the PolicyMembershipEvent table), which the
    Observatory renders separately. Keep the two concerns separate so this does
    not duplicate the membership-event fields.
    """

    policy_version_id: UUID
    player_id: str | None = None
    # The headline outcome the commissioner reached for this entrant this round
    # (e.g. "PROMOTED", "HELD", "3 wins"). Free-form; rendered verbatim.
    outcome: str
    # The numeric round score recorded for this entrant, when applicable.
    score: float | None = None
    passed: bool | None = None
    # Ordered calculation steps (inputs -> derivation -> output).
    steps: list[CommissionerCalcStep] = Field(default_factory=list)
    # One-line human explanation of the outcome.
    summary: str | None = None


class CommissionerRoundReport(BaseModel):
    """Structured, game-agnostic explanation of how a commissioner scored a round.

    The commissioner authors this; the platform persists it per round and the
    Observatory renders it so every scoring decision is inspectable end to end.
    Nothing here is game-specific in the schema — a game's commissioner fills in
    its own rule text, metric labels, and per-entrant calculation steps.
    """

    # Short id/name of the scoring rule in effect this round
    # (e.g. "skill_gate", "competition_wins", "mean_round_score").
    rule_id: str
    # Human-readable description of the active rule and how it computes outcomes.
    rule_description: str
    # Optional division this report pertains to (a round runs in one division).
    division_id: UUID | None = None
    # Per-entrant calculations.
    entrants: list[CommissionerEntrantReport] = Field(default_factory=list)
    # Free-form notes (e.g. dispatch-vs-crash classification, infra holds).
    notes: list[str] = Field(default_factory=list)
    # Arbitrary extra structured detail the commissioner wants surfaced.
    extra: dict[str, Any] = Field(default_factory=dict)
    # Optional self-contained HTML the commissioner authors to render its OWN view
    # of this round (e.g. a game-specific standings table, MMR board, bracket).
    # The platform embeds it in a sandboxed, script-disabled iframe, so it must
    # obey the safe-render profile (docs/artifacts/RENDER.md): no scripts, no
    # external resource loads (inline `data:` / same-document only), no embedding
    # or navigation sinks. Optional and additive; omit it to fall back to the
    # generic structured view rendered from the fields above.
    render_html: str | None = None


class RoundComplete(BaseModel):
    results: list[DivisionRanking] = Field(default_factory=list)
    leaderboards: list[DivisionLeaderboard] = Field(default_factory=list)
    policy_membership_events: list[PolicyMembershipEventChange] = Field(default_factory=list)
    membership_changes: list[MembershipChange] = Field(default_factory=list)
    round_display: dict[str, Any] | None = None
    state: Any = None
    # Structured, game-agnostic observability report describing HOW this round was
    # scored: the active rule, and per-entrant calculations (inputs -> derivation ->
    # output). The platform persists it per round and the Observatory renders it so
    # every scoring decision is fully inspectable. Optional and additive: a
    # commissioner that omits it loses no existing behavior.
    observability: CommissionerRoundReport | None = None

    @model_validator(mode="after")
    def fill_compatibility_leaderboards(self) -> "RoundComplete":
        # TODO: delete compatibility shim after old commissioners stop sending only results.
        if not self.leaderboards and self.results:
            self.leaderboards = [_leaderboard_from_division_ranking(result) for result in self.results]
        return self

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


class LeagueMigrationConfigRequest(BaseModel):
    league: LeagueInfo
    divisions: list[DivisionInfo]

    def to_json(self) -> dict[str, Any]:
        data = self.model_dump(mode="json")
        data["type"] = "league_migration_config_request"
        return data


class LeagueMigrationConfigResponse(BaseModel):
    divisions: list[DivisionConfig] = Field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        data = self.model_dump(mode="json")
        data["type"] = "league_migration_config_response"
        return data


class LeagueMigrationRequest(BaseModel):
    league: LeagueInfo
    divisions: list[DivisionInfo]
    memberships: list[MembershipInfo]

    def to_json(self) -> dict[str, Any]:
        data = self.model_dump(mode="json")
        data["type"] = "league_migration_request"
        return data


class LeagueMigrationResponse(BaseModel):
    policy_membership_events: list[PolicyMembershipEventChange] = Field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        data = self.model_dump(mode="json")
        data["type"] = "league_migration_response"
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
    default_view_key: str = "score"
    axes: list[DivisionLeaderboardAxis] = Field(default_factory=list)
    views: list[DivisionLeaderboardView] = Field(default_factory=list)
    # TODO: delete compatibility fields after platform and clients read generic `views`.
    primary_table_id: str | None = None
    tables: list[DivisionLeaderboardTable] = Field(default_factory=list)
    rankings: list[DivisionLeaderboardEntry] = Field(default_factory=list)

    @model_validator(mode="after")
    def fill_compatibility_fields(self) -> "RankDivisionResponse":
        if not self.views and self.tables:
            self.default_view_key = self.primary_table_id or self.tables[0].id
            self.views = [_view_from_table(table) for table in self.tables]
        if not self.views and self.rankings:
            self.views = [
                DivisionLeaderboardView(
                    key=self.default_view_key,
                    title="Score",
                    columns=_columns_for_entries(self.rankings),
                    rows=[_row_from_entry(entry) for entry in self.rankings],
                )
            ]
        if not self.views:
            self.views = [DivisionLeaderboardView(key=self.default_view_key)]
        if not any(view.key == self.default_view_key for view in self.views):
            self.default_view_key = self.views[0].key
        if not self.axes:
            self.axes = _axis_defs_from_views(self.views)
        if self.primary_table_id is None:
            self.primary_table_id = self.default_view_key
        if not self.tables:
            self.tables = [_table_from_view(view) for view in self.views]
        if not self.rankings:
            default_view = next((view for view in self.views if view.key == self.default_view_key), self.views[0])
            score_axis_key = _legacy_score_column_key(default_view)
            self.rankings = [
                _entry_from_row(row, rank, score_axis_key) for rank, row in enumerate(default_view.rows, start=1)
            ]
        return self

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
    policy_membership_events: list[PolicyMembershipEventChange] = Field(default_factory=list)
    membership_changes: list[MembershipChange] = Field(default_factory=list)
    follow_up_rounds: list[RoundSpec] = Field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        data = self.model_dump(mode="json")
        data["type"] = "round_completed_response"
        return data


class EpisodeCompletedResponse(BaseModel):
    episodes: list[EpisodeRequest] = Field(default_factory=list)
    policy_membership_events: list[PolicyMembershipEventChange] = Field(default_factory=list)

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
    | LeagueMigrationConfigRequest
    | LeagueMigrationRequest
    | RankDivisionRequest
    | DescribeDivisionRequest
    | RoundCompletedRequest
    | EpisodeCompletedRequest
)

CommissionerMessageType = (
    ScheduleEpisodes
    | EpisodeCancel
    | RoundComplete
    | ScheduleRoundsResponse
    | LeagueMigrationConfigResponse
    | LeagueMigrationResponse
    | RankDivisionResponse
    | DescribeDivisionResponse
    | RoundCompletedResponse
    | EpisodeCompletedResponse
)

_COMMISSIONER_MESSAGE_TYPES: dict[str, type[CommissionerMessageType]] = {
    "schedule_episodes": ScheduleEpisodes,
    "episode_cancel": EpisodeCancel,
    "round_complete": RoundComplete,
    "schedule_rounds_response": ScheduleRoundsResponse,
    "league_migration_config_response": LeagueMigrationConfigResponse,
    "league_migration_response": LeagueMigrationResponse,
    "rank_division_response": RankDivisionResponse,
    "describe_division_response": DescribeDivisionResponse,
    "round_completed_response": RoundCompletedResponse,
    "episode_completed_response": EpisodeCompletedResponse,
}


class CommissionerMessage:
    @staticmethod
    def from_json(data: dict[str, Any]) -> CommissionerMessageType:
        # TODO(protocol): move `type` into each message model as a Literal discriminator
        # and parse this with a Pydantic discriminated union instead of the custom
        # registry/to_json pattern.
        msg_type = data["type"]
        cls = _COMMISSIONER_MESSAGE_TYPES.get(msg_type)
        if cls is None:
            raise ValueError(f"Unknown commissioner message type: {msg_type!r}")
        return cls.model_validate({key: value for key, value in data.items() if key != "type"})


def default_competing_entrants(
    memberships: list[MembershipInfo],
    *,
    division_id: UUID,
) -> list[MembershipInfo]:
    return [
        membership
        for membership in memberships
        if membership.division_id == division_id
        and membership.status == POLICY_MEMBERSHIP_STATUS_COMPETING
        and membership.is_champion
    ]


def default_competing_membership_events(
    memberships: list[MembershipInfo],
    *,
    division_id: UUID,
    reason: str = "Default commissioner membership status assignment",
) -> list[PolicyMembershipEventChange]:
    desired_substatus_by_membership_id = {
        membership.id: POLICY_MEMBERSHIP_SUBSTATUS_ACTIVE
        if membership.is_champion
        else POLICY_MEMBERSHIP_SUBSTATUS_BENCHED
        for membership in memberships
        if membership.division_id == division_id and membership.status == POLICY_MEMBERSHIP_STATUS_COMPETING
    }
    return [
        PolicyMembershipEventChange(
            league_policy_membership_id=membership.id,
            from_division_id=membership.division_id,
            to_division_id=membership.division_id,
            status=POLICY_MEMBERSHIP_STATUS_COMPETING,
            substatus=desired_substatus_by_membership_id[membership.id],
            reason=reason,
        )
        for membership in memberships
        if membership.id in desired_substatus_by_membership_id
        and membership.substatus != desired_substatus_by_membership_id[membership.id]
    ]
