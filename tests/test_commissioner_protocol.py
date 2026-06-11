from uuid import uuid4

import pytest
from pydantic import ValidationError

from coworld.commissioner.protocol import (
    CommissionerMessage,
    DescribeDivisionResponse,
    DivisionDescription,
    DivisionInfo,
    DivisionRanking,
    EpisodeCompletedRequest,
    EpisodeCompletedResponse,
    EpisodeFailed,
    EpisodeRequest,
    EpisodeResult,
    EpisodeScore,
    LeagueInfo,
    MembershipChange,
    MembershipInfo,
    PolicyMembershipEventChange,
    RankingEntry,
    RoundComplete,
    RoundCompletedResponse,
    RoundConfig,
    RoundSpec,
    RoundStart,
    ScheduleEpisodes,
    ScheduleRoundsResponse,
    StageConfig,
    VariantInfo,
)


def test_round_start_serializes_with_message_type() -> None:
    league_id = uuid4()
    division_id = uuid4()
    membership_id = uuid4()
    policy_version_id = uuid4()
    round_start = RoundStart(
        round_id=uuid4(),
        round_number=7,
        league=LeagueInfo(id=league_id, commissioner_config={"minimum_champions": 8}),
        divisions=[DivisionInfo(id=division_id, name="Daily", level=1)],
        memberships=[
            MembershipInfo(
                id=membership_id,
                league_id=league_id,
                division_id=division_id,
                policy_version_id=policy_version_id,
                player_id="player_abc",
                status="competing",
                substatus="champion",
                is_champion=True,
            )
        ],
        recent_results=[],
        variants=[
            VariantInfo(
                id="among_them",
                name="Among Them",
                game_config={"tokens": ["a", "b"], "imposter_count": 1},
                num_agents=2,
            )
        ],
    )

    data = round_start.to_json()

    assert data["type"] == "round_start"
    assert data["league"]["id"] == str(league_id)
    assert data["memberships"][0]["policy_version_id"] == str(policy_version_id)
    assert data["memberships"][0]["is_champion"] is True
    assert data["variants"][0]["num_agents"] == 2


def test_commissioner_message_parses_schedule_episodes() -> None:
    policy_version_ids = [uuid4(), uuid4()]
    parsed = CommissionerMessage.from_json(
        {
            "type": "schedule_episodes",
            "episodes": [
                {
                    "request_id": "episode-1",
                    "variant_id": "among_them",
                    "policy_version_ids": [str(policy_version_id) for policy_version_id in policy_version_ids],
                    "seed": 42,
                    "tags": {"stage": "round"},
                }
            ],
        }
    )

    assert isinstance(parsed, ScheduleEpisodes)
    assert parsed.episodes == [
        EpisodeRequest(
            request_id="episode-1",
            variant_id="among_them",
            policy_version_ids=policy_version_ids,
            seed=42,
            tags={"stage": "round"},
        )
    ]


def test_commissioner_message_parses_round_complete_with_backend_metadata() -> None:
    division_id = uuid4()
    policy_version_id = uuid4()
    parsed = CommissionerMessage.from_json(
        {
            "type": "round_complete",
            "results": [
                {
                    "division_id": str(division_id),
                    "rankings": [
                        {
                            "policy_version_id": str(policy_version_id),
                            "player_id": "player_abc",
                            "rank": 1,
                            "score": 150.0,
                            "result_metadata": {"crew_wins": 3},
                        }
                    ],
                }
            ],
            "membership_changes": [
                {
                    "membership_id": str(uuid4()),
                    "from_division_id": str(division_id),
                    "to_division_id": str(uuid4()),
                    "reason": "promoted",
                }
            ],
            "round_display": {"tables": [{"id": "role_win_rates"}]},
            "state": {"next_seed": 5},
        }
    )

    assert isinstance(parsed, RoundComplete)
    assert parsed.results == [
        DivisionRanking(
            division_id=division_id,
            rankings=[
                RankingEntry(
                    policy_version_id=policy_version_id,
                    player_id="player_abc",
                    rank=1,
                    score=150.0,
                    result_metadata={"crew_wins": 3},
                )
            ],
        )
    ]
    assert parsed.round_display == {"tables": [{"id": "role_win_rates"}]}
    assert len(parsed.membership_changes) == 1
    assert parsed.to_json()["type"] == "round_complete"


def test_commissioner_message_parses_extended_hook_responses() -> None:
    division_id = uuid4()
    policy_version_ids = [uuid4(), uuid4()]
    parsed_schedule = CommissionerMessage.from_json(
        {
            "type": "schedule_rounds_response",
            "rounds": [
                {
                    "division_id": str(division_id),
                    "round_config": {"stages": [{"label": "Round", "num_episodes": 8, "self_play": True}]},
                    "execution_backend": "dispatch",
                }
            ],
        }
    )
    assert parsed_schedule == ScheduleRoundsResponse(
        rounds=[
            RoundSpec(
                division_id=division_id,
                round_config=RoundConfig(stages=[StageConfig(label="Round", num_episodes=8, self_play=True)]),
                execution_backend="dispatch",
            )
        ]
    )

    parsed_description = CommissionerMessage.from_json(
        {
            "type": "describe_division_response",
            "description": {"round_schedule": "Rounds start every ten minutes."},
        }
    )
    assert parsed_description == DescribeDivisionResponse(
        description=DivisionDescription(round_schedule="Rounds start every ten minutes.")
    )

    membership_id = uuid4()
    parsed_completed = CommissionerMessage.from_json(
        {
            "type": "round_completed_response",
            "membership_changes": [
                {
                    "membership_id": str(membership_id),
                    "from_division_id": str(division_id),
                    "is_active": False,
                    "reason": "did not qualify",
                }
            ],
        }
    )
    assert parsed_completed == RoundCompletedResponse(
        membership_changes=[
            MembershipChange(
                membership_id=membership_id,
                from_division_id=division_id,
                is_active=False,
                reason="did not qualify",
            )
        ]
    )

    parsed_episode_completed = CommissionerMessage.from_json(
        {
            "type": "episode_completed_response",
            "episodes": [
                {
                    "request_id": "retry-1",
                    "variant_id": "default",
                    "policy_version_ids": [str(policy_version_id) for policy_version_id in policy_version_ids],
                }
            ],
            "policy_membership_events": [
                {
                    "league_policy_membership_id": str(membership_id),
                    "from_division_id": str(division_id),
                    "to_division_id": str(division_id),
                    "status": "qualifying",
                    "substatus": "retry_pending",
                    "reason": "episode hook requested retry",
                }
            ],
        }
    )
    assert parsed_episode_completed == EpisodeCompletedResponse(
        episodes=[
            EpisodeRequest(
                request_id="retry-1",
                variant_id="default",
                policy_version_ids=policy_version_ids,
            )
        ],
        policy_membership_events=[
            PolicyMembershipEventChange(
                league_policy_membership_id=membership_id,
                from_division_id=division_id,
                to_division_id=division_id,
                status="qualifying",
                substatus="retry_pending",
                reason="episode hook requested retry",
            )
        ],
    )


def test_episode_completed_request_serializes_episode_result_and_failure() -> None:
    division_id = uuid4()
    policy_version_ids = [uuid4(), uuid4()]
    round_start = RoundStart(
        round_id=uuid4(),
        round_number=3,
        league=LeagueInfo(id=uuid4()),
        divisions=[DivisionInfo(id=division_id, name="Bronze", level=0)],
        memberships=[
            MembershipInfo(id=uuid4(), league_id=uuid4(), division_id=division_id, policy_version_id=policy_version_id)
            for policy_version_id in policy_version_ids
        ],
        recent_results=[],
        variants=[VariantInfo(id="default", name="Default", game_config={}, num_agents=2)],
    )
    result = EpisodeResult(
        request_id="episode-1",
        scores=[EpisodeScore(policy_version_id=policy_version_ids[0], score=1.0)],
    )

    result_request = EpisodeCompletedRequest(
        round_start=round_start,
        episode_result=result,
        completed_episode_results=[result],
    )
    failed_request = EpisodeCompletedRequest(
        round_start=round_start,
        episode_failed=EpisodeFailed(request_id="episode-2", error="container exited"),
        completed_episode_results=[result],
    )

    assert result_request.to_json()["type"] == "episode_completed_request"
    assert result_request.to_json()["episode_result"]["request_id"] == "episode-1"
    assert failed_request.to_json()["episode_failed"]["error"] == "container exited"


def test_episode_completed_request_requires_one_completed_event() -> None:
    round_start = RoundStart(
        round_id=uuid4(),
        round_number=3,
        league=LeagueInfo(id=uuid4()),
        divisions=[],
        memberships=[],
        recent_results=[],
        variants=[],
    )

    with pytest.raises(ValidationError, match="exactly one of episode_result or episode_failed"):
        EpisodeCompletedRequest(round_start=round_start)


def test_platform_episode_result_serializes_with_game_results() -> None:
    policy_version_id = uuid4()
    result = EpisodeResult(
        request_id="episode-1",
        scores=[EpisodeScore(policy_version_id=policy_version_id, player_id="player_abc", score=101.0)],
        game_results={"scores": [101.0]},
    )

    data = result.to_json()

    assert data["type"] == "episode_result"
    assert data["scores"][0]["policy_version_id"] == str(policy_version_id)
    assert data["game_results"] == {"scores": [101.0]}


def test_unknown_commissioner_message_type_fails() -> None:
    with pytest.raises(ValueError, match="Unknown commissioner message type"):
        CommissionerMessage.from_json({"type": "bogus"})


def test_round_complete_rejects_oversized_state() -> None:
    with pytest.raises(ValidationError, match="state must not exceed 10 MB"):
        RoundComplete(state={"payload": "x" * (10 * 1024 * 1024)})
