"""Extract recorded Paint Arena behavior without inventing unrecorded actions."""

from __future__ import annotations

import gzip
import hashlib
import zlib
from pathlib import Path
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StrictInt, model_validator

from coworld.stats import (
    EpisodeStats,
    MeasuredValue,
    MetricDefinition,
    MissingValue,
    NoOpportunities,
    SeatStats,
    StatsProvenance,
)


class PolicyIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")] | None


class ReplayInput(BaseModel):
    """Caller-supplied identities must come from the recorded episode receipt."""

    model_config = ConfigDict(extra="forbid")

    path: Path
    episode_id: str = Field(min_length=1)
    game_id: str = Field(min_length=1)
    game_build_id: str | None
    replay_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    policies: list[PolicyIdentity] = Field(min_length=1)
    context: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_provenance(self) -> Self:
        self.provenance()
        return self

    def provenance(self) -> StatsProvenance:
        return StatsProvenance(
            episode_id=self.episode_id,
            game_id=self.game_id,
            game_build_id=self.game_build_id,
            replay_sha256=self.replay_sha256,
            extractor_id="coworld.paintarena.replay",
            extractor_version=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            context=self.context,
        )


class _Config(BaseModel):
    width: int = Field(strict=True, gt=0)
    height: int = Field(strict=True, gt=0)
    max_ticks: int = Field(strict=True, gt=0)


class _Frame(BaseModel):
    tick: int = Field(strict=True, gt=0)
    positions: list[tuple[StrictInt, StrictInt]]
    tile_owners: list[StrictInt]
    scores: list[StrictInt]


class _Results(BaseModel):
    ticks: int = Field(strict=True, gt=0)
    scores: list[Annotated[float, Field(strict=True, allow_inf_nan=False)]]
    painted_tiles: list[StrictInt]


class _Replay(BaseModel):
    config: _Config
    player_names: list[str] = Field(min_length=1)
    frames: list[_Frame] = Field(min_length=1)
    results: _Results

    @model_validator(mode="after")
    def validate_episode(self) -> Self:
        count = len(self.player_names)
        if self.results.ticks != self.config.max_ticks or len(self.frames) != self.results.ticks:
            raise ValueError("Paint Arena stats require a complete episode with every recorded tick")
        for tick, frame in enumerate(self.frames, 1):
            if frame.tick != tick or len(frame.positions) != count or len(frame.scores) != count:
                raise ValueError("Replay tick sequence or seat count is inconsistent")
            if len(frame.tile_owners) != self.config.width * self.config.height:
                raise ValueError("Replay territory does not match the board dimensions")
            if any(owner < -1 or owner >= count for owner in frame.tile_owners):
                raise ValueError("Replay territory contains an unknown seat")
            if any(not (0 <= x < self.config.width and 0 <= y < self.config.height) for x, y in frame.positions):
                raise ValueError("Replay position lies outside the board")
            if frame.scores != [frame.tile_owners.count(seat) for seat in range(count)]:
                raise ValueError("Replay scores disagree with recorded territory")
        if self.results.scores != self.frames[-1].scores or self.results.painted_tiles != self.frames[-1].scores:
            raise ValueError("Terminal results disagree with the final replay frame")
        return self


METRICS = [
    MetricDefinition(
        id="paintarena.movement.executed_transitions",
        version=1,
        name="Executed movement",
        category="direct",
        unit="ticks",
        kind="count",
        description="Consecutive recorded ticks with changed position; excludes the unrecorded initial transition.",
        eligibility="Consecutive replay frames for this seat.",
        denominator=None,
        aggregation="Sum counts; retain episode and seat identities.",
        interpretation="Executed displacement, not the number of submitted commands.",
    ),
    MetricDefinition(
        id="paintarena.movement.active_fraction",
        version=1,
        name="Movement per recorded transition",
        category="direct",
        unit="fraction",
        kind="rate",
        description="Fraction of consecutive recorded ticks with changed position.",
        eligibility="Consecutive replay frames for this seat.",
        denominator="Number of frames minus one; the initial position is not recorded.",
        aggregation="Pool movement counts and transition denominators within a matched protocol.",
        interpretation="Behavioral frequency; more movement is not necessarily better.",
    ),
    MetricDefinition(
        id="paintarena.movement.submitted_commands",
        version=1,
        name="Submitted movement commands",
        category="direct",
        unit="commands",
        kind="count",
        description="Number of commands sent by the policy, including blocked movement and stay.",
        eligibility="Policy submissions during the episode.",
        denominator=None,
        aggregation="Sum only when the command stream is recorded.",
        interpretation="Cannot be reconstructed from positions because the last command persists between ticks.",
    ),
    MetricDefinition(
        id="paintarena.economy.purchase_fraction",
        version=1,
        name="Purchases when affordable",
        category="opportunity_dependent",
        unit="fraction",
        kind="rate",
        description="Fraction of eligible purchase decisions on which a purchase is made.",
        eligibility="The game offers an affordable purchase action.",
        denominator="Eligible purchase decisions.",
        aggregation="Pool counts only for games implementing the same purchase opportunity definition.",
        interpretation="Unsupported in Paint Arena, which has no purchase action or currency.",
    ),
    MetricDefinition(
        id="paintarena.territory.final_tiles",
        version=1,
        name="Final painted tiles",
        category="outcome",
        unit="tiles",
        kind="count",
        description="Tiles owned by this seat at the end of the episode, reconciled with native results.",
        eligibility="Complete native episode.",
        denominator=None,
        aggregation="Report per-episode values and their distribution within a matched protocol.",
        interpretation="Native terminal score; compare matched maps, seats, and opponents.",
    ),
]


def extract_stats(source: ReplayInput) -> EpisodeStats:
    raw = source.path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != source.replay_sha256:
        raise ValueError("Replay SHA-256 differs from the input manifest")
    if source.path.suffix == ".gz":
        raw = gzip.decompress(raw)
    elif source.path.suffix == ".z":
        raw = zlib.decompress(raw)
    replay = _Replay.model_validate_json(raw)
    if len(source.policies) != len(replay.player_names):
        raise ValueError("Policy identities must cover every replay seat in order")
    opportunities = len(replay.frames) - 1
    seats = []
    for seat, policy in enumerate(source.policies):
        moved = sum(
            before.positions[seat] != after.positions[seat]
            for before, after in zip(replay.frames[:-1], replay.frames[1:], strict=True)
        )
        score = replay.results.painted_tiles[seat]
        seats.append(
            SeatStats(
                seat_id=str(seat),
                policy_id=policy.id,
                policy_sha256=policy.sha256,
                measurements=[
                    MeasuredValue(
                        metric_id="paintarena.movement.executed_transitions",
                        status="measured",
                        value=moved,
                        count=moved,
                    ),
                    MeasuredValue(
                        metric_id="paintarena.movement.active_fraction",
                        status="measured",
                        value=moved / opportunities,
                        count=moved,
                        denominator=opportunities,
                    )
                    if opportunities
                    else NoOpportunities(metric_id="paintarena.movement.active_fraction", status="no_opportunities"),
                    MissingValue(
                        metric_id="paintarena.movement.submitted_commands",
                        status="missing",
                        reason="Native replay does not retain policy command submissions.",
                    ),
                    MissingValue(
                        metric_id="paintarena.economy.purchase_fraction",
                        status="unsupported",
                        reason="Paint Arena has no economy or purchase actions.",
                    ),
                    MeasuredValue(
                        metric_id="paintarena.territory.final_tiles", status="measured", value=score, count=score
                    ),
                ],
            )
        )
    return EpisodeStats(provenance=source.provenance(), metrics=METRICS, seats=seats)
