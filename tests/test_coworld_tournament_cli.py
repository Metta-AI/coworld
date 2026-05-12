import json
from pathlib import Path

import pytest
from pytest_httpserver import HTTPServer
from typer.testing import CliRunner

from coworld.cli import app

NOW = "2026-05-12T12:00:00Z"
GAME_ID = "game_00000000-0000-0000-0000-000000000010"
LEAGUE_ID = "league_00000000-0000-0000-0000-000000000011"
DIVISION_ID = "div_00000000-0000-0000-0000-000000000012"
ROUND_ID = "round_00000000-0000-0000-0000-000000000013"
POOL_ID = "pool_00000000-0000-0000-0000-000000000014"
COWORLD_ID = "cow_00000000-0000-0000-0000-000000000015"
EPISODE_REQUEST_ID = "ereq_00000000-0000-0000-0000-000000000016"
OTHER_EPISODE_REQUEST_ID = "ereq_00000000-0000-0000-0000-000000000017"
JOB_ID = "00000000-0000-0000-0000-000000000018"
EPISODE_ID = "00000000-0000-0000-0000-000000000019"
MY_POLICY_VERSION_ID = "00000000-0000-0000-0000-000000000031"
MY_POLICY_ID = "00000000-0000-0000-0000-000000000032"
OTHER_POLICY_VERSION_ID = "00000000-0000-0000-0000-000000000033"
OTHER_POLICY_ID = "00000000-0000-0000-0000-000000000034"


def test_replays_downloads_mine_division_replays(
    httpserver: HTTPServer,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("coworld.api_client._load_current_cogames_token", lambda: "token")
    replay_payload = b'{"frames":[]}\n'
    replay_url = httpserver.url_for("/replay.json")
    _expect_round_scope(httpserver)
    httpserver.expect_request(
        "/v2/episode-requests",
        method="GET",
        headers={"X-Auth-Token": "token"},
    ).respond_with_json(
        [
            _episode_request(episode_request_id=EPISODE_REQUEST_ID, replay_url=replay_url),
            _episode_request(
                episode_request_id=OTHER_EPISODE_REQUEST_ID,
                policy_version_id=OTHER_POLICY_VERSION_ID,
                policy_id=OTHER_POLICY_ID,
                policy_name="otherbot",
                replay_url=httpserver.url_for("/other-replay.json"),
            ),
        ]
    )
    _expect_mine_memberships(httpserver)
    httpserver.expect_request("/replay.json", method="GET").respond_with_data(replay_payload)

    result = CliRunner().invoke(
        app,
        [
            "replays",
            "--division",
            DIVISION_ID,
            "--mine",
            "--download-dir",
            str(tmp_path),
            "--server",
            httpserver.url_for(""),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    metadata = json.loads(result.output)
    assert [row["episode_request_id"] for row in metadata] == [EPISODE_REQUEST_ID]
    replay_path = tmp_path / f"{EPISODE_REQUEST_ID}.json"
    assert replay_path.read_bytes() == replay_payload
    index = json.loads((tmp_path / "index.json").read_text())
    assert index == metadata
    round_query = next(request for request, _ in httpserver.log if request.path == "/v2/rounds")
    assert round_query.args["division_id"] == DIVISION_ID
    membership_query = next(request for request, _ in httpserver.log if request.path == "/v2/league-policy-memberships")
    assert membership_query.args["mine"] == "true"
    assert membership_query.args["division_id"] == DIVISION_ID


def test_episode_stats_prints_job_stats_json(httpserver: HTTPServer, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("coworld.api_client._load_current_cogames_token", lambda: "token")
    httpserver.expect_request(
        f"/v2/episode-requests/{EPISODE_REQUEST_ID}",
        method="GET",
        headers={"X-Auth-Token": "token"},
    ).respond_with_json(_episode_request(episode_request_id=EPISODE_REQUEST_ID, replay_url=None))
    httpserver.expect_request(
        f"/jobs/{JOB_ID}/episode-stats",
        method="GET",
        headers={"X-Auth-Token": "token"},
    ).respond_with_json(
        {
            "game_stats": {"duration": 12.0},
            "policy_stats": [
                {
                    "position": 0,
                    "policy_version_id": MY_POLICY_VERSION_ID,
                    "policy_name": "paintbot",
                    "policy_version": 3,
                    "num_agents": 1,
                    "avg_metrics": {"tiles": 4.0},
                    "avg_reward": 1.25,
                    "agents": [{"agent_id": 0, "reward": 1.25, "metrics": {"tiles": 4.0}}],
                }
            ],
            "steps": 42,
        }
    )

    result = CliRunner().invoke(
        app,
        [
            "episode-stats",
            EPISODE_REQUEST_ID,
            "--server",
            httpserver.url_for(""),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["steps"] == 42
    assert payload["policy_stats"][0]["policy_name"] == "paintbot"
    assert payload["policy_stats"][0]["agents"][0]["agent_id"] == 0


def test_episode_logs_downloads_only_my_policy_agents(
    httpserver: HTTPServer,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("coworld.api_client._load_current_cogames_token", lambda: "token")
    httpserver.expect_request(
        f"/v2/episode-requests/{EPISODE_REQUEST_ID}",
        method="GET",
        headers={"X-Auth-Token": "token"},
    ).respond_with_json(_episode_request(episode_request_id=EPISODE_REQUEST_ID, replay_url=None))
    httpserver.expect_request(
        f"/jobs/{JOB_ID}/policy-logs",
        method="GET",
        headers={"X-Auth-Token": "token"},
    ).respond_with_json(["policy_agent_0.txt", "policy_agent_1.txt"])
    _expect_mine_memberships(httpserver, division_id=None)
    httpserver.expect_request(
        f"/jobs/{JOB_ID}/policy-logs/0",
        method="GET",
        headers={"X-Auth-Token": "token"},
    ).respond_with_data("mine log\n", content_type="text/plain")

    result = CliRunner().invoke(
        app,
        [
            "episode-logs",
            EPISODE_REQUEST_ID,
            "--mine",
            "--download-dir",
            str(tmp_path),
            "--server",
            httpserver.url_for(""),
        ],
    )

    assert result.exit_code == 0, result.output
    assert (tmp_path / f"{EPISODE_REQUEST_ID}-policy_agent_0.txt").read_text() == "mine log\n"
    assert not (tmp_path / f"{EPISODE_REQUEST_ID}-policy_agent_1.txt").exists()


def _expect_round_scope(httpserver: HTTPServer) -> None:
    httpserver.expect_request(
        "/v2/rounds",
        method="GET",
        headers={"X-Auth-Token": "token"},
    ).respond_with_json({"entries": [_round_public()], "total_count": 1, "limit": 200, "offset": 0})
    httpserver.expect_request(
        f"/v2/rounds/{ROUND_ID}",
        method="GET",
        headers={"X-Auth-Token": "token"},
    ).respond_with_json(_round_detail())


def _expect_mine_memberships(httpserver: HTTPServer, *, division_id: str | None = DIVISION_ID) -> None:
    httpserver.expect_request(
        "/v2/league-policy-memberships",
        method="GET",
        headers={"X-Auth-Token": "token"},
    ).respond_with_json([_membership(division_id=division_id or DIVISION_ID)])


def _game() -> dict[str, object]:
    return {
        "id": GAME_ID,
        "name": "Paint Arena",
        "slug": "paint-arena",
        "coworld_name": "paint-arena",
        "coworld_id": COWORLD_ID,
        "created_at": NOW,
    }


def _league() -> dict[str, object]:
    return {
        "id": LEAGUE_ID,
        "name": "Paint League",
        "slug": "paint",
        "game": _game(),
        "commissioner_key": "auto",
        "public": True,
        "hidden": False,
        "created_at": NOW,
    }


def _division(division_id: str = DIVISION_ID) -> dict[str, object]:
    return {
        "id": division_id,
        "name": "Bronze",
        "level": 1,
        "league": _league(),
        "description": "Bronze division",
        "created_at": NOW,
    }


def _round_public() -> dict[str, object]:
    return {
        "id": ROUND_ID,
        "round_number": 7,
        "commissioner_key": "auto",
        "execution_backend": "dispatch",
        "round_config": {},
        "round_display": None,
        "status": "completed",
        "division": _division(),
        "created_at": NOW,
    }


def _round_detail() -> dict[str, object]:
    return {**_round_public(), "pools": [_pool()], "results": []}


def _pool() -> dict[str, object]:
    return {
        "id": POOL_ID,
        "round_id": ROUND_ID,
        "pool_index": 0,
        "label": "Pool A",
        "pool_type": "round_robin",
        "env_config": None,
        "coworld_id": COWORLD_ID,
        "config": {},
        "status": "completed",
        "created_at": NOW,
    }


def _membership(*, division_id: str = DIVISION_ID) -> dict[str, object]:
    return {
        "id": "lpm_00000000-0000-0000-0000-000000000051",
        "is_active": True,
        "is_champion": False,
        "start_time": NOW,
        "league": _league(),
        "division": _division(division_id),
        "policy_version": _policy_version(
            policy_version_id=MY_POLICY_VERSION_ID,
            policy_id=MY_POLICY_ID,
            policy_name="paintbot",
            version=3,
        ),
        "player": {"id": "player_00000000-0000-0000-0000-000000000061", "name": "Me"},
        "created_at": NOW,
    }


def _policy_version(
    *,
    policy_version_id: str,
    policy_id: str,
    policy_name: str,
    version: int,
) -> dict[str, object]:
    return {
        "id": policy_version_id,
        "policy": {"id": policy_id, "name": policy_name},
        "version": version,
        "player_id": "player_00000000-0000-0000-0000-000000000061",
    }


def _episode_request(
    *,
    episode_request_id: str,
    replay_url: str | None,
    policy_version_id: str = MY_POLICY_VERSION_ID,
    policy_id: str = MY_POLICY_ID,
    policy_name: str = "paintbot",
) -> dict[str, object]:
    return {
        "id": episode_request_id,
        "requester_user_id": "user_00000000-0000-0000-0000-000000000071",
        "pool_id": POOL_ID,
        "mod_name": None,
        "env_config_name": "paintarena-default",
        "coworld_id": COWORLD_ID,
        "seed": 123,
        "assignments": [0, 1],
        "max_steps": 1000,
        "status": "completed",
        "policy_version_ids": [policy_version_id, OTHER_POLICY_VERSION_ID],
        "participants": [
            {
                "position": 0,
                "policy_version_id": policy_version_id,
                "policy_id": policy_id,
                "policy_name": policy_name,
                "version": 3,
                "player_id": "player_00000000-0000-0000-0000-000000000061",
                "player_name": "Me",
            },
            {
                "position": 1,
                "policy_version_id": OTHER_POLICY_VERSION_ID,
                "policy_id": OTHER_POLICY_ID,
                "policy_name": "otherbot",
                "version": 1,
                "player_id": "player_00000000-0000-0000-0000-000000000062",
                "player_name": "Other",
            },
        ],
        "job_id": JOB_ID,
        "episode_id": EPISODE_ID,
        "replay_url": replay_url,
        "scores": [
            {"policy_version_id": policy_version_id, "score": 1.25},
            {"policy_version_id": OTHER_POLICY_VERSION_ID, "score": 0.5},
        ],
        "created_at": NOW,
    }
