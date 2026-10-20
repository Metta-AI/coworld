from __future__ import annotations

import math
from typing import Annotated, Literal, Optional, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

COWORLD_STATS_SCHEMA_URI = "https://softmax.com/api/observatory/v2/reporters/schemas/coworld.stats.v1.json"

NonEmptyText = Annotated[str, Field(min_length=1, pattern=r"\S")]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Count = Annotated[int, Field(strict=True, ge=0)]
FiniteValue = Annotated[float, Field(strict=True, allow_inf_nan=False)]


class _StatsModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class MetricDefinition(_StatsModel):
    id: NonEmptyText
    version: Annotated[int, Field(strict=True, ge=1)]
    name: NonEmptyText
    category: Literal["direct", "opportunity_dependent", "outcome"]
    unit: NonEmptyText
    kind: Literal["count", "rate", "value"] = Field(
        description="Rate is a fraction of eligible opportunities in [0, 1]; use value for other ratios or frequencies."
    )
    description: NonEmptyText
    eligibility: NonEmptyText = Field(description="Which events or decisions qualify for this metric.")
    denominator: Optional[NonEmptyText] = Field(description="Rate denominator semantics; null for counts and values.")
    aggregation: NonEmptyText = Field(
        description="How observations may be combined, including weighting and exclusions."
    )
    interpretation: NonEmptyText = Field(description="Meaning and limits; behavior statistics do not establish intent.")

    @model_validator(mode="after")
    def validate_denominator(self) -> Self:
        if (self.kind == "rate") != (self.denominator is not None):
            raise ValueError("Only rate metrics must declare denominator semantics")
        return self


class MeasuredValue(_StatsModel):
    metric_id: NonEmptyText
    status: Literal["measured"]
    value: FiniteValue
    count: Optional[Count] = None
    denominator: Optional[Annotated[int, Field(strict=True, gt=0)]] = None


class MissingValue(_StatsModel):
    metric_id: NonEmptyText
    status: Literal["missing", "unsupported"]
    reason: NonEmptyText


class NoOpportunities(_StatsModel):
    metric_id: NonEmptyText
    status: Literal["no_opportunities"]
    count: Annotated[int, Field(strict=True, ge=0, le=0)] = 0
    denominator: Annotated[int, Field(strict=True, ge=0, le=0)] = 0


Measurement = Annotated[MeasuredValue | MissingValue | NoOpportunities, Field(discriminator="status")]


class SeatStats(_StatsModel):
    seat_id: NonEmptyText
    policy_id: Optional[NonEmptyText] = Field(
        description="Recorded policy identity, or null when absent from the source."
    )
    policy_sha256: Optional[Sha256] = Field(description="Policy artifact SHA-256, or null when unavailable.")
    measurements: list[Measurement] = Field(min_length=1)


class StatsProvenance(_StatsModel):
    episode_id: NonEmptyText = Field(
        description="Recorded episode ID, or replay-sha256:<digest> for an unlabelled replay."
    )
    game_id: NonEmptyText
    game_build_id: Optional[NonEmptyText] = Field(
        description="Immutable game build identity, or null when unavailable."
    )
    replay_sha256: Sha256 = Field(description="SHA-256 of the exact replay bytes consumed by the extractor.")
    extractor_id: NonEmptyText
    extractor_version: NonEmptyText = Field(description="Version identifying the extraction algorithm and semantics.")
    context: dict[str, JsonValue] = Field(
        default_factory=dict,
        description="Recorded variant, scenario seed, or evaluation protocol. Missing keys cannot establish matching.",
    )

    @model_validator(mode="after")
    def validate_replay_identity(self) -> Self:
        if self.episode_id.startswith("replay-sha256:") and self.episode_id != f"replay-sha256:{self.replay_sha256}":
            raise ValueError("Replay-derived episode ID must match the source replay SHA-256")
        return self


class EpisodeStats(_StatsModel):
    """One episode's registry and complete per-seat observations, including unavailable measurements."""

    provenance: StatsProvenance
    metrics: list[MetricDefinition] = Field(min_length=1)
    seats: list[SeatStats] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_measurements(self) -> Self:
        registry = {metric.id: metric for metric in self.metrics}
        if len(registry) != len(self.metrics):
            raise ValueError("Metric IDs must be unique within a stats block")
        if len({seat.seat_id for seat in self.seats}) != len(self.seats):
            raise ValueError("Seat IDs must be unique within an episode")
        for seat in self.seats:
            metric_ids = [measurement.metric_id for measurement in seat.measurements]
            if len(set(metric_ids)) != len(metric_ids) or set(metric_ids) != set(registry):
                raise ValueError(f"Seat {seat.seat_id} must report each registered metric exactly once")
            for measurement in seat.measurements:
                metric = registry[measurement.metric_id]
                if isinstance(measurement, MissingValue):
                    continue
                if isinstance(measurement, NoOpportunities):
                    if metric.kind != "rate":
                        raise ValueError(f"{metric.id}: no_opportunities requires a rate metric")
                    continue
                if metric.kind == "rate":
                    if measurement.count is None or measurement.denominator is None:
                        raise ValueError(f"{metric.id}: measured rates require a count and positive denominator")
                    if measurement.count > measurement.denominator or not 0 <= measurement.value <= 1:
                        raise ValueError(f"{metric.id}: rate counts cannot exceed eligible opportunities")
                    if not math.isclose(measurement.value, measurement.count / measurement.denominator, rel_tol=1e-9):
                        raise ValueError(f"{metric.id}: rate must equal count / denominator")
                elif metric.kind == "count":
                    if measurement.count is None or measurement.value != measurement.count:
                        raise ValueError(f"{metric.id}: count value must equal its integer count")
                    if measurement.denominator is not None:
                        raise ValueError(f"{metric.id}: counts cannot have a denominator")
                elif measurement.count is not None or measurement.denominator is not None:
                    raise ValueError(f"{metric.id}: value metrics cannot have counts or denominators")
        return self


class StatsFailure(_StatsModel):
    provenance: StatsProvenance
    reason: NonEmptyText


class StatsBlock(_StatsModel):
    """A reporter's episode statistics and explicit extraction failures."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "$id": COWORLD_STATS_SCHEMA_URI,
            "$schema": "https://json-schema.org/draft/2020-12/schema",
        },
    )

    schema_version: Literal["coworld.stats.v1"]
    episodes: list[EpisodeStats]
    failures: list[StatsFailure]

    @model_validator(mode="after")
    def validate_episodes(self) -> Self:
        episode_ids = [episode.provenance.episode_id for episode in self.episodes]
        episode_ids.extend(failure.provenance.episode_id for failure in self.failures)
        if not episode_ids:
            raise ValueError("A stats block requires at least one episode or extraction failure")
        if len(set(episode_ids)) != len(episode_ids):
            raise ValueError("Episode IDs must be unique across statistics and extraction failures")
        definitions: dict[tuple[str, int], MetricDefinition] = {}
        for episode in self.episodes:
            for metric in episode.metrics:
                key = (metric.id, metric.version)
                if key in definitions and definitions[key] != metric:
                    raise ValueError(f"{metric.id} v{metric.version}: definitions must agree across episodes")
                definitions[key] = metric
        return self


def get_coworld_stats_schema() -> dict[str, JsonValue]:
    return StatsBlock.model_json_schema()
