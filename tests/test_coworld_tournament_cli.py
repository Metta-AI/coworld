import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

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
        "/observatory/v2/episode-requests",
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
    round_query = next(request for request, _ in httpserver.log if request.path == "/observatory/v2/rounds")
    assert round_query.args["division_id"] == DIVISION_ID
    membership_query = next(
        request for request, _ in httpserver.log if request.path == "/observatory/v2/league-policy-memberships"
    )
    assert membership_query.args["mine"] == "true"
    assert membership_query.args["division_id"] == DIVISION_ID


def test_episode_stats_prints_job_stats_json(httpserver: HTTPServer, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("coworld.api_client._load_current_cogames_token", lambda: "token")
    httpserver.expect_request(
        f"/observatory/v2/episode-requests/{EPISODE_REQUEST_ID}",
        method="GET",
        headers={"X-Auth-Token": "token"},
    ).respond_with_json(_episode_request(episode_request_id=EPISODE_REQUEST_ID, replay_url=None))
    httpserver.expect_request(
        f"/observatory/jobs/{JOB_ID}/episode-stats",
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


def test_episodes_accepts_bulk_rows_without_assignments(
    httpserver: HTTPServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("coworld.api_client._load_current_cogames_token", lambda: "token")
    _expect_round_scope(httpserver)
    episode_request = _episode_request(episode_request_id=EPISODE_REQUEST_ID, replay_url=None)
    del episode_request["assignments"]
    httpserver.expect_request(
        "/observatory/v2/episode-requests",
        method="GET",
        headers={"X-Auth-Token": "token"},
    ).respond_with_json([episode_request])

    result = CliRunner().invoke(
        app,
        [
            "episodes",
            "--round",
            ROUND_ID,
            "--server",
            httpserver.url_for(""),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    rows = json.loads(result.output)
    assert rows[0]["id"] == EPISODE_REQUEST_ID
    assert "assignments" not in rows[0]


def test_episode_logs_downloads_only_my_policy_agents(
    httpserver: HTTPServer,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("coworld.api_client._load_current_cogames_token", lambda: "token")
    episode_request = _episode_request(episode_request_id=EPISODE_REQUEST_ID, replay_url=None)
    del episode_request["assignments"]
    httpserver.expect_request(
        f"/observatory/v2/episode-requests/{EPISODE_REQUEST_ID}",
        method="GET",
        headers={"X-Auth-Token": "token"},
    ).respond_with_json(episode_request)
    httpserver.expect_request(
        f"/observatory/jobs/{JOB_ID}/policy-logs",
        method="GET",
        headers={"X-Auth-Token": "token"},
    ).respond_with_json(["policy_agent_0.log", "policy_agent_1.log"])
    _expect_mine_memberships(httpserver, division_id=None)
    httpserver.expect_request(
        f"/observatory/jobs/{JOB_ID}/policy-logs/0",
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
    assert (tmp_path / f"{EPISODE_REQUEST_ID}-policy_agent_0.log").read_text() == "mine log\n"
    assert not (tmp_path / f"{EPISODE_REQUEST_ID}-policy_agent_1.log").exists()


def test_episode_logs_downloads_game_log(
    httpserver: HTTPServer,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("coworld.api_client._load_current_cogames_token", lambda: "token")
    httpserver.expect_request(
        f"/observatory/v2/episode-requests/{EPISODE_REQUEST_ID}",
        method="GET",
        headers={"X-Auth-Token": "token"},
    ).respond_with_json(_episode_request(episode_request_id=EPISODE_REQUEST_ID, replay_url=None))
    httpserver.expect_request(
        f"/observatory/v2/episode-requests/{EPISODE_REQUEST_ID}/artifacts/logs",
        method="GET",
        headers={"X-Auth-Token": "token"},
    ).respond_with_data("game log\n", content_type="text/plain")

    result = CliRunner().invoke(
        app,
        [
            "episode-logs",
            EPISODE_REQUEST_ID,
            "--game",
            "--download-dir",
            str(tmp_path),
            "--server",
            httpserver.url_for(""),
        ],
    )

    assert result.exit_code == 0, result.output
    assert (tmp_path / f"{EPISODE_REQUEST_ID}-game.log").read_text() == "game log\n"


def test_replay_open_downloads_only_game_image_for_local_replay(
    httpserver: HTTPServer,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("coworld.api_client._load_current_cogames_token", lambda: "token")
    replay_path = tmp_path / "replay.json"
    replay_path.write_text('{"frames":[]}\n')
    httpserver.expect_request(
        f"/observatory/v2/episode-requests/{EPISODE_REQUEST_ID}",
        method="GET",
        headers={"X-Auth-Token": "token"},
    ).respond_with_json(_episode_request(episode_request_id=EPISODE_REQUEST_ID, replay_url=replay_path.as_uri()))

    calls: dict[str, Any] = {}
    game_image = "public.ecr.aws/example/unit-test-game:latest"
    player_image = "private.example.com/unit-test-player:latest"

    def fake_download_coworld(coworld_ref: str, *, server: str) -> Any:
        calls["download"] = {"coworld_ref": coworld_ref, "server": server}
        return SimpleNamespace(
            id=COWORLD_ID,
            name="unit-test-game",
            version="0.1.0",
            manifest={
                "game": {"runnable": {"image": game_image}},
                "player": [{"image": player_image}],
            },
        )

    def fake_docker_run(command: list[str], **kwargs: Any) -> Any:
        calls.setdefault("docker", []).append((command, kwargs))
        return SimpleNamespace()

    def fake_replay_coworld(
        manifest_path: Path,
        replay_path: Path,
        *,
        timeout_seconds: float,
        on_ready: Callable[[Any], None],
    ) -> Any:
        calls["replay"] = {
            "manifest": json.loads(manifest_path.read_text(encoding="utf-8")),
            "manifest_path": manifest_path,
            "replay_path": replay_path,
            "timeout_seconds": timeout_seconds,
        }
        artifacts = SimpleNamespace(workspace=tmp_path / "artifacts", logs_dir=tmp_path / "logs")
        session = SimpleNamespace(artifacts=artifacts, replay_path=replay_path, link="http://replay.local")
        on_ready(session)
        return session

    monkeypatch.setattr("coworld.tournament_cli.download_coworld", fake_download_coworld)
    monkeypatch.setattr("coworld.upload.subprocess.run", fake_docker_run)
    monkeypatch.setattr("coworld.tournament_cli.replay_coworld", fake_replay_coworld)

    result = CliRunner().invoke(
        app,
        [
            "replay-open",
            EPISODE_REQUEST_ID,
            "--server",
            httpserver.url_for(""),
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls["download"] == {
        "coworld_ref": COWORLD_ID,
        "server": httpserver.url_for(""),
    }
    assert [call[0] for call in calls["docker"]] == [
        ["docker", "pull", game_image],
        ["docker", "tag", game_image, f"coworld/{COWORLD_ID}/replay-game:downloaded"],
    ]
    replay_call = calls["replay"]
    assert replay_call["manifest"]["game"]["runnable"]["image"] == f"coworld/{COWORLD_ID}/replay-game:downloaded"
    assert replay_call["manifest"]["player"][0]["image"] == player_image
    assert replay_call["replay_path"] == replay_path
    assert "Replay client: http://replay.local" in result.output


def _expect_round_scope(httpserver: HTTPServer) -> None:
    httpserver.expect_request(
        "/observatory/v2/rounds",
        method="GET",
        headers={"X-Auth-Token": "token"},
    ).respond_with_json({"entries": [_round_public()], "total_count": 1, "limit": 200, "offset": 0})
    httpserver.expect_request(
        f"/observatory/v2/rounds/{ROUND_ID}",
        method="GET",
        headers={"X-Auth-Token": "token"},
    ).respond_with_json(_round_detail())


def _expect_mine_memberships(httpserver: HTTPServer, *, division_id: str | None = DIVISION_ID) -> None:
    httpserver.expect_request(
        "/observatory/v2/league-policy-memberships",
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
