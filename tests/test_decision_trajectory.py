import base64
from pathlib import Path
from typing import Literal
from uuid import uuid4

import pytest

from coworld.decision_trajectory import (
    CompleteEpisode,
    DecisionAttempt,
    DecisionEvent,
    EpisodeEvent,
    ExecutionEvidence,
    complete_episodes,
    export_complete_episodes,
    read_trajectory_jsonl,
)


@pytest.mark.parametrize(
    ("encoding", "controls"),
    [
        ("i8-i8-i8-u8", b"\x00\xff\x01\x02\x00\xff\x01\x02"),
        ("u8", b"\x00\xff"),
        ("u8-u8", b"\x00\xff\x01\x02"),
    ],
)
def test_physical_execution_preserves_macro_action_and_exact_controls(
    tmp_path: Path, encoding: Literal["i8-i8-i8-u8", "u8", "u8-u8"], controls: bytes
) -> None:
    execution = ExecutionEvidence(
        start_tick=10,
        end_tick=12,
        tick_hz=60,
        control_encoding=encoding,
        seat_controls_b64=base64.b64encode(controls).decode(),
    )
    decision = _decision("physical-episode", 0).model_copy(update={"execution": execution})
    source = tmp_path / "physical.jsonl"
    source.write_text(decision.model_dump_json() + "\n")
    assert list(read_trajectory_jsonl(source)) == [decision]
    assert decision.executed_action == {"action": 0}
    assert isinstance(decision.execution, ExecutionEvidence)
    assert base64.b64decode(decision.execution.seat_controls_b64) == controls
    complete = tmp_path / "complete.jsonl"
    summary = EpisodeEvent(episode_id="physical-episode", seed_family="physical-seed", game="test", status="completed")
    assert export_complete_episodes([decision, summary], complete) == 1
    assert list(read_trajectory_jsonl(complete)) == [decision, summary]


@pytest.mark.parametrize(
    "evidence",
    [
        {"response_body_b64": "invalid!"},
        {"response_headers_b64": "invalid!"},
        {"response_body_b64": "e30=", "raw_response": "different bytes"},
        {"response_complete": "false"},
        {"response_reader_joined": "false"},
        {"http_status": True},
    ],
)
def test_received_response_rejects_malformed_or_conflicting_evidence(evidence: dict) -> None:
    with pytest.raises(ValueError):
        DecisionAttempt(attempt_id="invalid", policy="learner", origin="model", accepted=False, **evidence)


@pytest.mark.parametrize(
    "changes",
    [
        {"end_tick": 10},
        {"end_tick": 9},
        {"end_tick": 13},
        {"tick_hz": 0},
        {"tick_hz": float("inf")},
        {"seat_controls_b64": "invalid base64!"},
        {"control_encoding": "u8"},
        {"control_encoding": "u8-u8"},
    ],
)
def test_physical_execution_rejects_invalid_tick_evidence(changes: dict) -> None:
    with pytest.raises(ValueError):
        ExecutionEvidence.model_validate(
            {
                "start_tick": 10,
                "end_tick": 12,
                "tick_hz": 60,
                "control_encoding": "i8-i8-i8-u8",
                "seat_controls_b64": "AP8BAgD/AQI=",
                **changes,
            }
        )


def _decision(episode_id: str, index: int, *, version: str | None = "v1") -> DecisionEvent:
    call_id = uuid4()
    return DecisionEvent(
        episode_id=episode_id,
        decision_id=f"turn-{index}",
        decision_index=index,
        game="any-game",
        game_version=version,
        seat="seat-a",
        prompt={"messages": [{"role": "user", "content": "act"}]},
        attempts=[
            DecisionAttempt(
                attempt_id=f"attempt-{index}",
                platform_call_id=call_id,
                policy="frontier-teacher",
                origin="teacher",
                response={"action": index},
                parsed_action={"action": index},
                accepted=True,
            )
        ],
        selected_attempt_id=f"attempt-{index}",
        executed_action={"action": index},
        action_status="accepted",
    )


def test_truncated_episode_is_not_exported() -> None:
    episode_id = "episode-1"
    events = [
        _decision(episode_id, 0),
        EpisodeEvent(episode_id=episode_id, seed_family="family-1", game="any-game", status="truncated"),
    ]

    assert list(complete_episodes(events)) == []


def test_closed_episode_is_released_before_loading_the_next_page() -> None:
    first_consumed = False
    first = _complete_episode()
    second = _decision("episode-2", 0)

    def pages():
        yield from first.decisions
        yield first.episode
        assert first_consumed
        yield second
        yield first.episode.model_copy(update={"episode_id": "episode-2"})

    episodes = complete_episodes(pages())
    assert next(episodes) == first
    first_consumed = True
    assert [record.episode.episode_id for record in episodes] == ["episode-2"]


def test_incomplete_tail_does_not_publish_a_completed_export(tmp_path: Path) -> None:
    first = _complete_episode()
    destination = tmp_path / "episodes.jsonl"
    events = [*first.decisions, first.episode, _decision("episode-2", 0)]

    with pytest.raises(ValueError, match="must have exactly one summary"):
        export_complete_episodes(events, destination)
    assert not destination.exists()


def test_interleaved_episodes_keep_first_appearance_order() -> None:
    first = _complete_episode()
    second = _decision("episode-2", 0)
    events = [
        first.decisions[0],
        second,
        first.episode.model_copy(update={"episode_id": "episode-2"}),
        first.episode,
    ]
    assert [record.episode.episode_id for record in complete_episodes(events)] == ["episode-1", "episode-2"]


def test_unknown_seed_family_roundtrips_completed_engine_evidence(tmp_path: Path) -> None:
    record = _complete_episode()
    summary = record.episode.model_copy(update={"seed_family": None})
    source = tmp_path / "unknown-family.jsonl"
    assert export_complete_episodes([*record.decisions, summary], source) == 1
    (loaded,) = complete_episodes(read_trajectory_jsonl(source))
    assert loaded.episode.status == "completed" and loaded.episode.seed_family is None
    assert loaded.decisions == record.decisions


def _complete_episode() -> CompleteEpisode:
    decision = _decision("episode-1", 0)
    return CompleteEpisode(
        episode=EpisodeEvent(
            episode_id="episode-1",
            seed_family="family",
            game="any-game",
            game_version="v1",
            source_revision="a" * 40,
            status="completed",
            outcome={"score": 1},
        ),
        decisions=[decision],
    )
