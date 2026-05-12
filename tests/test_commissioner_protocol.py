from uuid import uuid4

import pytest
from pydantic import ValidationError

from coworld.commissioner.protocol import (
    CommissionerMessage,
    DivisionInfo,
    DivisionRanking,
    EpisodeRequest,
    EpisodeResult,
    EpisodeScore,
    LeagueInfo,
    MembershipInfo,
    RankingEntry,
    RoundComplete,
    RoundStart,
    ScheduleEpisodes,
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
                division_id=division_id,
                policy_version_id=policy_version_id,
                player_id="player_abc",
                is_champion=True,
            )
        ],
        recent_results=[],
        variants=[
            VariantInfo(
                id="among_them",
                name="Among Them",
                game_config={"tokens": ["a", "b"], "imposter_count": 1},
            )
        ],
    )

    data = round_start.to_json()

    assert data["type"] == "round_start"
    assert data["league"]["id"] == str(league_id)
    assert data["memberships"][0]["policy_version_id"] == str(policy_version_id)


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
            "graduation_changes": [],
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
    assert parsed.to_json()["type"] == "round_complete"


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
