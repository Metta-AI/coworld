"""Provider-neutral game decision telemetry and complete-episode export.

The game runtime is the authority for executed actions.  This contract keeps
model attempts linked to the platform call that produced them, while allowing
each game to carry its own observation, action, and outcome JSON.  It does not
depend on replay timestamps or a particular game version.

Game runtimes emit typed events directly; complete episodes retain their original
order and applied-action evidence through JSONL export.
"""

import base64
import os
from collections import defaultdict, deque
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StrictBool, StrictInt, TypeAdapter, model_validator


class DecisionAttempt(BaseModel):
    """One proposal made while resolving a game decision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    attempt_id: str = Field(min_length=1)
    platform_call_id: UUID | None = None
    generation_id: str | None = Field(default=None, min_length=1)
    policy: str = Field(min_length=1)
    origin: Literal["model", "teacher", "fallback", "human", "unknown"]
    inference_mode: str | None = None
    provider_request: JsonValue | None = None
    provider_response: JsonValue | None = None
    prompt: JsonValue | None = None
    request: JsonValue | None = None
    response: JsonValue | None = None
    raw_response: JsonValue | None = None
    response_headers: dict[str, str] | None = None
    response_body_b64: str | None = None
    response_headers_b64: str | None = None
    response_complete: StrictBool | None = None
    response_reader_joined: StrictBool | None = None
    http_status: StrictInt | None = Field(default=None, ge=100, le=599)
    provider_request_id: str | None = Field(default=None, min_length=1)
    model: str | None = Field(default=None, min_length=1)
    model_identity: str | None = Field(default=None, min_length=1)
    tokenizer_identity: str | None = Field(default=None, min_length=1)
    chat_template_sha256: str | None = Field(default=None, min_length=1)
    decoder: JsonValue | None = None
    prompt_token_ids: list[int] | None = None
    sampled_token_ids: list[int] | None = None
    stop_reason: str | None = Field(default=None, min_length=1)
    parsed_action: JsonValue | None = None
    accepted: bool
    rejection_reason: str | None = Field(default=None, min_length=1)
    latency_ms: float | None = Field(default=None, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    behavior_logprobs: list[float] | None = None

    @model_validator(mode="after")
    def validate_received_response(self) -> "DecisionAttempt":
        if self.response_body_b64 is not None:
            body = base64.b64decode(self.response_body_b64, validate=True)
            if isinstance(self.raw_response, str) and body != self.raw_response.encode("utf-8"):
                raise ValueError("Received body bytes differ from raw response")
        if self.response_headers_b64 is not None:
            base64.b64decode(self.response_headers_b64, validate=True)
        return self


class ExecutionEvidence(BaseModel):
    """Engine-owned physical controls for an applied macro action.

    Ticks cover [start_tick, end_tick). The encoding is either three signed
    bytes (move_x, move_y, aim_turn) plus one unsigned action byte, or one
    unsigned motor/input-mask byte per tick for this seat. Two unsigned bytes
    encode the movement action and vibe action consumed by MettaGrid per tick.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    start_tick: int = Field(ge=0)
    end_tick: int = Field(ge=0)
    tick_hz: float = Field(gt=0, allow_inf_nan=False)
    control_encoding: Literal["i8-i8-i8-u8", "u8", "u8-u8"]
    seat_controls_b64: str

    @model_validator(mode="after")
    def validate_controls(self) -> "ExecutionEvidence":
        if self.end_tick <= self.start_tick:
            raise ValueError("execution must contain at least one physical tick")
        controls = base64.b64decode(self.seat_controls_b64, validate=True)
        stride = {"i8-i8-i8-u8": 4, "u8": 1, "u8-u8": 2}[self.control_encoding]
        if len(controls) != stride * (self.end_tick - self.start_tick):
            raise ValueError(f"execution controls must contain exactly {stride} bytes per tick")
        return self


class DecisionEvent(BaseModel):
    """Authoritative result of one game decision, including every attempt."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1"] = "1"
    event_type: Literal["decision"] = "decision"
    event_id: UUID = Field(default_factory=uuid4)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    episode_id: str = Field(min_length=1)
    decision_id: str = Field(min_length=1)
    decision_index: int = Field(ge=0)
    game: str = Field(min_length=1)
    game_version: str | None = Field(default=None, min_length=1)
    source_revision: str | None = Field(default=None, min_length=1)
    image_digest: str | None = Field(default=None, min_length=1)
    seat: str = Field(min_length=1)
    visibility: Literal["private", "public", "mixed", "unknown"] = "private"
    observation: JsonValue | None = None
    prompt: JsonValue | None = None
    attempts: list[DecisionAttempt]
    selected_attempt_id: str | None = Field(default=None, min_length=1)
    executed_action: JsonValue | None = None
    execution: ExecutionEvidence | None = None
    action_status: Literal["accepted", "rejected", "fallback", "missing"]
    fallback_origin: str | None = Field(default=None, min_length=1)
    reward: JsonValue | None = None
    terminal: bool = False


class EpisodeEvent(BaseModel):
    """Terminal or truncated episode summary emitted by the game runtime."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1"] = "1"
    event_type: Literal["episode"] = "episode"
    event_id: UUID = Field(default_factory=uuid4)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    episode_id: str = Field(min_length=1)
    seed_family: str | None = Field(min_length=1)
    game: str = Field(min_length=1)
    game_version: str | None = Field(default=None, min_length=1)
    source_revision: str | None = Field(default=None, min_length=1)
    image_digest: str | None = Field(default=None, min_length=1)
    status: Literal["completed", "truncated", "failed"]
    outcome: JsonValue | None = None
    participant_outcomes: JsonValue | None = None


TrajectoryEvent = Annotated[DecisionEvent | EpisodeEvent, Field(discriminator="event_type")]


class CompleteEpisode(BaseModel):
    """Export unit containing only decisions from a completed episode."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1"] = "1"
    episode: EpisodeEvent
    decisions: list[DecisionEvent]


_TRAJECTORY_RECORD_ADAPTER = TypeAdapter(TrajectoryEvent | CompleteEpisode)


def complete_episodes(events: Iterable[TrajectoryEvent]) -> Iterator[CompleteEpisode]:
    """Validate and yield complete episodes without timestamp-based joins."""

    grouped: dict[str, list[TrajectoryEvent]] = defaultdict(list)
    ordered: deque[str] = deque()
    ended: set[str] = set()
    for event in events:
        if event.episode_id in ended:
            raise ValueError(f"episode {event.episode_id} continues after its summary")
        if event.episode_id not in grouped:
            ordered.append(event.episode_id)
        if isinstance(event, EpisodeEvent):
            ended.add(event.episode_id)
        grouped[event.episode_id].append(event)
        while ordered and ordered[0] in ended:
            episode_id = ordered.popleft()
            episode_events = grouped.pop(episode_id)
            summary = next(event for event in episode_events if isinstance(event, EpisodeEvent))
            if summary.status != "completed":
                continue
            decisions = sorted(
                (event for event in episode_events if isinstance(event, DecisionEvent)),
                key=lambda event: event.decision_index,
            )
            if [event.decision_index for event in decisions] != list(range(len(decisions))):
                raise ValueError(f"episode {episode_id} has non-contiguous decision indexes")
            if len({event.decision_id for event in decisions}) != len(decisions):
                raise ValueError(f"episode {episode_id} has duplicate decision ids")
            yield CompleteEpisode(episode=summary, decisions=decisions)
    if ordered:
        raise ValueError(f"episode {ordered[0]} must have exactly one summary")


def export_complete_episodes(events: Iterable[TrajectoryEvent], destination: Path) -> int:
    """Write complete episodes as one validated JSON object per line."""

    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    partial = destination.with_name(f".{destination.name}.{uuid4()}.partial")
    descriptor = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    count = 0
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        for episode in complete_episodes(events):
            stream.write(episode.model_dump_json() + "\n")
            count += 1
        stream.flush()
        os.fsync(stream.fileno())
    os.link(partial, destination)
    partial.unlink()
    return count


def read_trajectory_jsonl(source: Path) -> Iterator[TrajectoryEvent]:
    """Validate event streams and engine-owned complete-episode envelopes line by line."""

    with source.open(encoding="utf-8") as stream:
        yield from parse_trajectory_jsonl(stream)


def parse_trajectory_jsonl(lines: Iterable[str]) -> Iterator[TrajectoryEvent]:
    """Parse captured bytes without reopening a changing artifact during export."""
    for line in lines:
        if not line.strip():
            continue
        record = _TRAJECTORY_RECORD_ADAPTER.validate_json(line)
        if isinstance(record, CompleteEpisode):
            yield from record.decisions
            yield record.episode
        else:
            yield record
