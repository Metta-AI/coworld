from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from coworld.commissioner.protocol import (
    CommissionerCalcStep,
    CommissionerEntrantReport,
    CommissionerMessage,
    CommissionerRoundReport,
    DescribeDivisionResponse,
    DivisionConfig,
    DivisionDescription,
    DivisionInfo,
    DivisionLeaderboard,
    DivisionLeaderboardAxis,
    DivisionLeaderboardColumn,
    DivisionLeaderboardEntry,
    DivisionLeaderboardRow,
    DivisionLeaderboardTable,
    DivisionLeaderboardView,
    DivisionRanking,
    EpisodeCompletedRequest,
    EpisodeCompletedResponse,
    EpisodeFailed,
    EpisodeRequest,
    EpisodeResult,
    EpisodeScore,
    LeagueInfo,
    LeagueMigrationConfigRequest,
    LeagueMigrationConfigResponse,
    LeagueMigrationRequest,
    LeagueMigrationResponse,
    MembershipChange,
    MembershipInfo,
    PolicyMembershipEventChange,
    RankDivisionResponse,
    RankingEntry,
    RecentResult,
    RoundComplete,
    RoundCompletedResponse,
    RoundConfig,
    RoundSpec,
    RoundStart,
    ScheduleEpisodes,
    ScheduleRoundsResponse,
    StageConfig,
    VariantInfo,
    default_competing_entrants,
    default_competing_membership_events,
)
from coworld.report import assert_safe_render_html


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
                substatus="active",
                is_champion=True,
            )
        ],
        recent_results=[],
        variants=[
            VariantInfo(
                id="among_them",
                name="Among Them",
                game_config={"tokens": ["a", "b"], "imposter_count": 1},
                # TODO(commissioner-rollout): remove this assertion fixture with
                # the deprecated `VariantInfo.num_agents` wire-compat field.
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


def test_default_competing_helpers_use_is_champion_and_emit_commissioner_substatuses() -> None:
    league_id = uuid4()
    division_id = uuid4()
    other_division_id = uuid4()
    champion = MembershipInfo(
        id=uuid4(),
        league_id=league_id,
        division_id=division_id,
        policy_version_id=uuid4(),
        status="competing",
        substatus="benched",
        is_champion=True,
    )
    benched = MembershipInfo(
        id=uuid4(),
        league_id=league_id,
        division_id=division_id,
        policy_version_id=uuid4(),
        status="competing",
        substatus=None,
        is_champion=False,
    )
    qualifier = MembershipInfo(
        id=uuid4(),
        league_id=league_id,
        division_id=division_id,
        policy_version_id=uuid4(),
        status="qualifying",
        is_champion=True,
    )
    other_division_champion = MembershipInfo(
        id=uuid4(),
        league_id=league_id,
        division_id=other_division_id,
        policy_version_id=uuid4(),
        status="competing",
        is_champion=True,
    )

    memberships = [champion, benched, qualifier, other_division_champion]

    assert default_competing_entrants(memberships, division_id=division_id) == [champion]
    events = default_competing_membership_events(memberships, division_id=division_id)

    assert [(event.league_policy_membership_id, event.substatus) for event in events] == [
        (champion.id, "active"),
        (benched.id, "benched"),
    ]
    assert all(event.status == "competing" for event in events)
    assert all(event.from_division_id == division_id and event.to_division_id == division_id for event in events)


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


def test_commissioner_message_parses_league_migration_responses() -> None:
    membership_id = uuid4()
    division_id = uuid4()
    target_division_id = uuid4()

    parsed_config = CommissionerMessage.from_json(
        {
            "type": "league_migration_config_response",
            "divisions": [
                {
                    "name": "Competition",
                    "previous_name": "Daily",
                    "level": 1,
                    "type": "competition",
                    "description": "Main ladder",
                }
            ],
        }
    )
    assert parsed_config == LeagueMigrationConfigResponse(
        divisions=[
            DivisionConfig(
                name="Competition",
                previous_name="Daily",
                level=1,
                type="competition",
                description="Main ladder",
            )
        ]
    )

    parsed_migration = CommissionerMessage.from_json(
        {
            "type": "league_migration_response",
            "policy_membership_events": [
                {
                    "league_policy_membership_id": str(membership_id),
                    "from_division_id": str(division_id),
                    "to_division_id": str(target_division_id),
                    "status": "competing",
                    "substatus": "champion",
                    "reason": "legacy tier migration",
                }
            ],
        }
    )
    assert parsed_migration == LeagueMigrationResponse(
        policy_membership_events=[
            PolicyMembershipEventChange(
                league_policy_membership_id=membership_id,
                from_division_id=division_id,
                to_division_id=target_division_id,
                status="competing",
                substatus="champion",
                reason="legacy tier migration",
            )
        ]
    )


def test_league_migration_requests_serialize_with_message_type() -> None:
    league_id = uuid4()
    division_id = uuid4()
    membership_id = uuid4()
    policy_version_id = uuid4()
    league = LeagueInfo(id=league_id, commissioner_config={"mode": "daily"})
    divisions = [DivisionInfo(id=division_id, name="Daily", level=1)]
    memberships = [
        MembershipInfo(
            id=membership_id,
            league_id=league_id,
            division_id=division_id,
            policy_version_id=policy_version_id,
            status="competing",
        )
    ]

    config_request = LeagueMigrationConfigRequest(league=league, divisions=divisions)
    migration_request = LeagueMigrationRequest(league=league, divisions=divisions, memberships=memberships)

    assert config_request.to_json()["type"] == "league_migration_config_request"
    assert config_request.to_json()["divisions"][0]["id"] == str(division_id)
    assert migration_request.to_json()["type"] == "league_migration_request"
    assert migration_request.to_json()["memberships"][0]["policy_version_id"] == str(policy_version_id)


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
        variants=[VariantInfo(id="default", name="Default", game_config={})],
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


def test_recent_result_completed_at_requires_serialized_string() -> None:
    # completed_at is a wire field typed `str | None`: callers must pre-serialize the
    # round's completion timestamp (e.g. datetime.isoformat()). Passing a raw datetime
    # is rejected by Pydantic, which is what broke every tournament round when the field
    # was added while a construction site still passed Round.completed_at unconverted.
    base = dict(round_id=uuid4(), division_id=uuid4(), round_number=1, policy_version_id=uuid4(), rank=1, score=1.0)
    completed_at = datetime(2026, 6, 25, 17, 0, tzinfo=timezone.utc)

    with pytest.raises(ValidationError, match="completed_at"):
        RecentResult(**base, completed_at=completed_at)

    assert RecentResult(**base, completed_at=completed_at.isoformat()).completed_at == "2026-06-25T17:00:00+00:00"
    assert RecentResult(**base, completed_at=None).completed_at is None


def test_rank_division_response_fills_rankings_from_default_view() -> None:
    response = RankDivisionResponse(
        default_view_key="winrate_24h",
        views=[
            DivisionLeaderboardView(key="score", title="Score"),
            DivisionLeaderboardView(
                key="winrate_24h",
                title="Winrate 24h",
                axis_values={"metric": "winrate", "timeframe": "24h"},
                columns=[
                    DivisionLeaderboardColumn(key="rank", label="Rank", value_type="integer", sort="asc"),
                    DivisionLeaderboardColumn(key="winrate", label="Winrate", value_type="number", sort="desc"),
                ],
                rows=[
                    DivisionLeaderboardRow(
                        subject_id="player_1",
                        values={"rank": 1, "winrate": 0.75, "rounds_played": 3},
                    )
                ],
            ),
        ],
    )

    assert response.rankings[0].player_id == "player_1"
    assert response.rankings[0].score == 0.75
    assert response.axes == [
        DivisionLeaderboardAxis(key="metric", label="Metric"),
        DivisionLeaderboardAxis(key="timeframe", label="Timeframe"),
    ]
    assert response.to_json()["views"][1]["rows"][0]["values"]["winrate"] == 0.75


def test_rank_division_response_fills_view_from_legacy_rankings() -> None:
    entry = DivisionLeaderboardEntry(
        player_id="player_1",
        rank=1,
        score=2.0,
        rounds_played=1,
    )

    response = RankDivisionResponse(rankings=[entry])

    assert response.views[0].key == "score"
    assert response.views[0].columns[1].key == "score"
    assert response.views[0].rows[0].values["score"] == 2.0
    assert response.rankings == [entry]


def test_rank_division_response_fills_view_from_legacy_table() -> None:
    entry = DivisionLeaderboardEntry(
        player_id="player_1",
        rank=1,
        score=0.75,
        rounds_played=3,
    )

    response = RankDivisionResponse(
        primary_table_id="winrate_24h",
        tables=[
            DivisionLeaderboardTable(id="score", label="Score", score_label="Score", rankings=[]),
            DivisionLeaderboardTable(
                id="winrate_24h",
                label="Winrate 24h",
                score_label="Winrate",
                rankings=[entry],
            ),
        ],
    )

    assert response.default_view_key == "winrate_24h"
    assert response.views[1].key == "winrate_24h"
    assert response.views[1].columns[1].label == "Winrate"
    assert response.rankings == [entry]


def test_round_complete_fills_leaderboards_from_legacy_results() -> None:
    division_id = uuid4()
    policy_version_id = uuid4()

    complete = RoundComplete(
        results=[
            DivisionRanking(
                division_id=division_id,
                rankings=[
                    RankingEntry(
                        policy_version_id=policy_version_id,
                        player_id="player_1",
                        rank=1,
                        score=4.0,
                    )
                ],
            )
        ]
    )

    assert complete.leaderboards[0].division_id == division_id
    assert complete.leaderboards[0].axes == [
        DivisionLeaderboardAxis(key="metric", label="Metric"),
        DivisionLeaderboardAxis(key="timeframe", label="Timeframe"),
    ]
    assert complete.leaderboards[0].views[0].axis_values == {"metric": "score", "timeframe": "legacy"}
    assert complete.leaderboards[0].views[0].rows[0].values == {"rank": 1, "score": 4.0}


def test_round_complete_preserves_explicit_leaderboards() -> None:
    division_id = uuid4()
    leaderboard = DivisionLeaderboard(
        division_id=division_id,
        default_view_key="score_1h",
        axes=[DivisionLeaderboardAxis(key="timeframe", label="Timeframe")],
        views=[DivisionLeaderboardView(key="score_1h", axis_values={"timeframe": "1h"})],
    )

    complete = RoundComplete(leaderboards=[leaderboard])

    assert complete.leaderboards == [leaderboard]


def test_round_complete_carries_structured_observability_report() -> None:
    pv = uuid4()
    report = CommissionerRoundReport(
        rule_id="best_episode_score",
        rule_description="Round score = best episode score.",
        entrants=[
            CommissionerEntrantReport(
                policy_version_id=pv,
                player_id="ply_x",
                outcome="42 pts",
                score=42.0,
                steps=[CommissionerCalcStep(label="best episode score", value=42.0, inputs={"episodes_scored": 3})],
                summary="best of 3 episodes",
            )
        ],
        notes=["scored 3 episodes"],
    )
    complete = RoundComplete(observability=report)

    # Round-trips through the wire encoding the platform uses.
    rehydrated = RoundComplete.model_validate({k: v for k, v in complete.to_json().items() if k != "type"})
    assert rehydrated.observability is not None
    assert rehydrated.observability.rule_id == "best_episode_score"
    assert rehydrated.observability.entrants[0].policy_version_id == pv
    assert rehydrated.observability.entrants[0].steps[0].value == 42.0


def test_round_complete_observability_defaults_to_none() -> None:
    assert RoundComplete().observability is None


def test_round_report_render_html_round_trips_and_is_safe() -> None:
    html = (
        "<!doctype html><html><head><style>td{padding:4px}</style></head>"
        "<body><table><tr><td>p1</td><td>42</td></tr></table></body></html>"
    )
    report = CommissionerRoundReport(
        rule_id="best_episode_score",
        rule_description="best of N",
        render_html=html,
    )
    rehydrated = RoundComplete.model_validate(
        {k: v for k, v in RoundComplete(observability=report).to_json().items() if k != "type"}
    )
    assert rehydrated.observability is not None
    assert rehydrated.observability.render_html == html
    # The authored sample obeys the safe-render profile the platform enforces.
    assert_safe_render_html(html)


def test_round_report_render_html_defaults_to_none() -> None:
    report = CommissionerRoundReport(rule_id="r", rule_description="d")
    assert report.render_html is None
