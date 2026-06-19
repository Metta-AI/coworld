import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import pytest
from pytest_httpserver import HTTPServer
from typer.testing import CliRunner

from coworld.api_client import CoworldApiClient, _load_current_token
from coworld.cli import app

NOW = "2026-05-12T12:00:00Z"
GAME_ID = "game_00000000-0000-0000-0000-000000000010"
LEAGUE_ID = "league_00000000-0000-0000-0000-000000000011"
DIVISION_ID = "div_00000000-0000-0000-0000-000000000012"
ROUND_ID = "round_00000000-0000-0000-0000-000000000013"
ROUND_ID = "rnd_00000000-0000-0000-0000-000000000014"
COWORLD_ID = "cow_00000000-0000-0000-0000-000000000015"
EPISODE_REQUEST_ID = "ereq_00000000-0000-0000-0000-000000000016"
OTHER_EPISODE_REQUEST_ID = "ereq_00000000-0000-0000-0000-000000000017"
JOB_ID = "00000000-0000-0000-0000-000000000018"
EPISODE_ID = "00000000-0000-0000-0000-000000000019"
MY_POLICY_VERSION_ID = "00000000-0000-0000-0000-000000000031"
MY_POLICY_ID = "00000000-0000-0000-0000-000000000032"
OTHER_POLICY_VERSION_ID = "00000000-0000-0000-0000-000000000033"
OTHER_POLICY_ID = "00000000-0000-0000-0000-000000000034"


@pytest.fixture(autouse=True)
def _fake_softmax_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("softmax.auth.load_current_token", lambda *, server: "token")


def test_api_client_token_lookup_uses_server_url(monkeypatch: pytest.MonkeyPatch) -> None:
    requested_servers: list[str] = []

    def fake_load_current_token(*, server: str) -> str:
        requested_servers.append(server)
        return "token"

    monkeypatch.setattr("softmax.auth.load_current_token", fake_load_current_token)

    assert _load_current_token(server_url="http://localhost:3102/api") == "token"
    assert requested_servers == ["http://localhost:3102/api"]


def test_api_client_auth_error_mentions_server_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("softmax.auth.load_current_token", lambda *, server: None)

    with pytest.raises(RuntimeError) as exc_info:
        CoworldApiClient.from_login(server_url="http://localhost:3102/api")

    assert "uv run softmax login --server http://localhost:3102/api" in str(exc_info.value)


def test_replays_downloads_mine_division_replays(
    httpserver: HTTPServer,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    replay_payload = b"\x00crewrift-replay-bytes\xff"
    replay_url = httpserver.url_for("/replay")
    httpserver.expect_request(
        "/observatory/v2/episode-requests",
        method="GET",
        headers={"Authorization": "Bearer token"},
    ).respond_with_json(
        {
            "entries": [
                _episode_request(episode_request_id=EPISODE_REQUEST_ID, replay_url=replay_url),
                _episode_request(
                    episode_request_id=OTHER_EPISODE_REQUEST_ID,
                    policy_version_id=OTHER_POLICY_VERSION_ID,
                    policy_id=OTHER_POLICY_ID,
                    policy_name="otherbot",
                    replay_url=httpserver.url_for("/other-replay"),
                ),
            ],
            "total_count": 2,
            "limit": 1000,
            "offset": 0,
        }
    )
    _expect_mine_memberships(httpserver)
    httpserver.expect_request("/replay", method="GET").respond_with_data(replay_payload)

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
    replay_path = tmp_path / f"{EPISODE_REQUEST_ID}.replay"
    assert replay_path.read_bytes() == replay_payload
    index = json.loads((tmp_path / "index.json").read_text())
    assert index == metadata
    episode_query = next(request for request, _ in httpserver.log if request.path == "/observatory/v2/episode-requests")
    assert episode_query.args["division_id"] == DIVISION_ID
    assert not any(request.path == "/observatory/v2/rounds" for request, _ in httpserver.log)
    membership_query = next(
        request for request, _ in httpserver.log if request.path == "/observatory/v2/league-policy-memberships"
    )
    assert membership_query.args["mine"] == "true"
    assert membership_query.args["division_id"] == DIVISION_ID


def test_episode_stats_prints_job_stats_json(httpserver: HTTPServer, monkeypatch: pytest.MonkeyPatch) -> None:
    httpserver.expect_request(
        f"/observatory/v2/episode-requests/{EPISODE_REQUEST_ID}",
        method="GET",
        headers={"Authorization": "Bearer token"},
    ).respond_with_json(_episode_request(episode_request_id=EPISODE_REQUEST_ID, replay_url=None))
    httpserver.expect_request(
        f"/observatory/jobs/{JOB_ID}/episode-stats",
        method="GET",
        headers={"Authorization": "Bearer token"},
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


def test_results_handles_empty_division_leaderboard(httpserver: HTTPServer) -> None:
    # The endpoint returns JSON null for divisions with no completed rounds.
    httpserver.expect_request(
        f"/observatory/v2/divisions/{DIVISION_ID}/leaderboard",
        method="GET",
        headers={"Authorization": "Bearer token"},
    ).respond_with_json(None)

    result = CliRunner().invoke(
        app,
        [
            "results",
            DIVISION_ID,
            "--server",
            httpserver.url_for(""),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == []


def test_episodes_accepts_bulk_rows_without_assignments(
    httpserver: HTTPServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    episode_request = _episode_request(episode_request_id=EPISODE_REQUEST_ID, replay_url=None)
    del episode_request["assignments"]
    httpserver.expect_request(
        "/observatory/v2/episode-requests",
        method="GET",
        headers={"Authorization": "Bearer token"},
    ).respond_with_json({"entries": [episode_request], "total_count": 1, "limit": 1000, "offset": 0})

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
    episode_query = next(request for request, _ in httpserver.log if request.path == "/observatory/v2/episode-requests")
    assert episode_query.args["round_id"] == ROUND_ID
    assert not any(request.path == "/observatory/v2/rounds" for request, _ in httpserver.log)


def test_episodes_mine_division_uses_direct_episode_query(
    httpserver: HTTPServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    httpserver.expect_request(
        "/observatory/v2/episode-requests",
        method="GET",
        headers={"Authorization": "Bearer token"},
    ).respond_with_json(
        {
            "entries": [_episode_request(episode_request_id=EPISODE_REQUEST_ID, replay_url="s3://replay")],
            "total_count": 1,
            "limit": 1000,
            "offset": 0,
        }
    )
    _expect_mine_memberships(httpserver)

    result = CliRunner().invoke(
        app,
        [
            "episodes",
            "--division",
            DIVISION_ID,
            "--mine",
            "--with-replay",
            "--server",
            httpserver.url_for(""),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    rows = json.loads(result.output)
    assert [row["id"] for row in rows] == [EPISODE_REQUEST_ID]
    episode_query = next(request for request, _ in httpserver.log if request.path == "/observatory/v2/episode-requests")
    assert episode_query.args["division_id"] == DIVISION_ID
    assert not any(request.path == "/observatory/v2/rounds" for request, _ in httpserver.log)


def test_memberships_accepts_status_substatus_payload(
    httpserver: HTTPServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    httpserver.expect_request(
        "/observatory/v2/league-policy-memberships",
        method="GET",
        headers={"Authorization": "Bearer token"},
    ).respond_with_json([_membership(substatus="champion")])

    result = CliRunner().invoke(
        app,
        [
            "memberships",
            "--mine",
            "--server",
            httpserver.url_for(""),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    rows = json.loads(result.output)
    assert rows[0]["status"] == "competing"
    assert rows[0]["substatus"] == "champion"
    assert "is_active" not in rows[0]
    assert rows[0]["is_champion"] is False


def test_retire_membership_posts_reason_json(
    httpserver: HTTPServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("coworld.api_client._load_current_token", lambda *, server_url: "token")
    membership_id = "lpm_00000000-0000-0000-0000-000000000051"
    reason = "Broken action names hang qualifiers."
    httpserver.expect_request(
        f"/observatory/v2/league-policy-memberships/{membership_id}/retire",
        method="POST",
        headers={"Authorization": "Bearer token"},
        json={"reason": reason},
    ).respond_with_json(
        _membership(
            status="disqualified",
            substatus="inactive",
            end_time=NOW,
        )
    )

    result = CliRunner().invoke(
        app,
        [
            "retire-membership",
            membership_id,
            "--reason",
            reason,
            "--server",
            httpserver.url_for(""),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["id"] == membership_id
    assert payload["status"] == "disqualified"
    assert payload["substatus"] == "inactive"


def test_episode_logs_downloads_only_my_policy_agents(
    httpserver: HTTPServer,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    episode_request = _episode_request(episode_request_id=EPISODE_REQUEST_ID, replay_url=None)
    del episode_request["assignments"]
    httpserver.expect_request(
        f"/observatory/v2/episode-requests/{EPISODE_REQUEST_ID}",
        method="GET",
        headers={"Authorization": "Bearer token"},
    ).respond_with_json(episode_request)
    httpserver.expect_request(
        f"/observatory/jobs/{JOB_ID}/policy-logs",
        method="GET",
        headers={"Authorization": "Bearer token"},
    ).respond_with_json(["policy_agent_0.log", "policy_agent_1.log"])
    httpserver.expect_request(
        f"/observatory/jobs/{JOB_ID}/policy-artifact",
        method="GET",
        headers={"Authorization": "Bearer token"},
    ).respond_with_json(["policy_artifact_0.zip"])
    _expect_mine_memberships(httpserver, division_id=None)
    httpserver.expect_request(
        f"/observatory/jobs/{JOB_ID}/policy-logs/0",
        method="GET",
        headers={"Authorization": "Bearer token"},
    ).respond_with_data("mine log\n", content_type="text/plain")
    httpserver.expect_request(
        f"/observatory/v2/episode-requests/{EPISODE_REQUEST_ID}/{MY_POLICY_VERSION_ID}/policy-artifact/0",
        method="GET",
        headers={"Authorization": "Bearer token"},
    ).respond_with_data(b"PK\x03\x04mine zip", content_type="application/zip")

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
    # Agent 0 also has an artifact, so it is downloaded alongside the log; agent 1 is not mine.
    assert (tmp_path / f"{EPISODE_REQUEST_ID}-policy_agent_0.zip").read_bytes() == b"PK\x03\x04mine zip"
    assert not (tmp_path / f"{EPISODE_REQUEST_ID}-policy_agent_1.zip").exists()


def test_episode_logs_agent_download_dir_fetches_both_log_and_artifact(
    httpserver: HTTPServer,
    tmp_path: Path,
) -> None:
    episode_request = _episode_request(episode_request_id=EPISODE_REQUEST_ID, replay_url=None)
    del episode_request["assignments"]
    httpserver.expect_request(
        f"/observatory/v2/episode-requests/{EPISODE_REQUEST_ID}",
        method="GET",
    ).respond_with_json(episode_request)
    httpserver.expect_request(
        f"/observatory/jobs/{JOB_ID}/policy-logs",
        method="GET",
    ).respond_with_json(["policy_agent_0.log", "policy_agent_1.log"])
    httpserver.expect_request(
        f"/observatory/jobs/{JOB_ID}/policy-artifact",
        method="GET",
    ).respond_with_json(["policy_artifact_0.zip"])
    httpserver.expect_request(
        f"/observatory/jobs/{JOB_ID}/policy-logs/0",
        method="GET",
    ).respond_with_data("agent0 log\n", content_type="text/plain")
    httpserver.expect_request(
        f"/observatory/v2/episode-requests/{EPISODE_REQUEST_ID}/{MY_POLICY_VERSION_ID}/policy-artifact/0",
        method="GET",
    ).respond_with_data(b"PK\x03\x04agent0 zip", content_type="application/zip")

    result = CliRunner().invoke(
        app,
        [
            "episode-logs",
            EPISODE_REQUEST_ID,
            "--agent",
            "0",
            "--download-dir",
            str(tmp_path),
            "--server",
            httpserver.url_for(""),
        ],
    )

    assert result.exit_code == 0, result.output
    assert (tmp_path / f"{EPISODE_REQUEST_ID}-policy_agent_0.log").read_text() == "agent0 log\n"
    assert (tmp_path / f"{EPISODE_REQUEST_ID}-policy_agent_0.zip").read_bytes() == b"PK\x03\x04agent0 zip"


def test_episode_logs_agent_view_prints_artifact_hint(
    httpserver: HTTPServer,
) -> None:
    episode_request = _episode_request(episode_request_id=EPISODE_REQUEST_ID, replay_url=None)
    del episode_request["assignments"]
    httpserver.expect_request(
        f"/observatory/v2/episode-requests/{EPISODE_REQUEST_ID}",
        method="GET",
    ).respond_with_json(episode_request)
    httpserver.expect_request(
        f"/observatory/jobs/{JOB_ID}/policy-logs",
        method="GET",
    ).respond_with_json(["policy_agent_0.log"])
    httpserver.expect_request(
        f"/observatory/jobs/{JOB_ID}/policy-artifact",
        method="GET",
    ).respond_with_json(["policy_artifact_0.zip"])
    httpserver.expect_request(
        f"/observatory/jobs/{JOB_ID}/policy-logs/0",
        method="GET",
    ).respond_with_data("agent0 log\n", content_type="text/plain")

    result = CliRunner().invoke(
        app,
        [
            "episode-logs",
            EPISODE_REQUEST_ID,
            "--agent",
            "0",
            "--server",
            httpserver.url_for(""),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "agent0 log" in result.output
    assert "uploaded a player artifact" in result.output
    assert "--artifact" in result.output
    # Viewing must not silently download the artifact bytes.
    assert not any(request.path.endswith("/policy-artifact/0") for request, _ in httpserver.log)


def test_episode_logs_downloads_game_log(
    httpserver: HTTPServer,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    httpserver.expect_request(
        f"/observatory/v2/episode-requests/{EPISODE_REQUEST_ID}",
        method="GET",
        headers={"Authorization": "Bearer token"},
    ).respond_with_json(_episode_request(episode_request_id=EPISODE_REQUEST_ID, replay_url=None))
    httpserver.expect_request(
        f"/observatory/v2/episode-requests/{EPISODE_REQUEST_ID}/artifacts/logs",
        method="GET",
        headers={"Authorization": "Bearer token"},
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


def test_episode_logs_downloads_player_artifact(
    httpserver: HTTPServer,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    episode_request = _episode_request(episode_request_id=EPISODE_REQUEST_ID, replay_url=None)
    del episode_request["assignments"]
    httpserver.expect_request(
        f"/observatory/v2/episode-requests/{EPISODE_REQUEST_ID}",
        method="GET",
        headers={"Authorization": "Bearer token"},
    ).respond_with_json(episode_request)
    httpserver.expect_request(
        f"/observatory/jobs/{JOB_ID}/policy-artifact",
        method="GET",
        headers={"Authorization": "Bearer token"},
    ).respond_with_json(["policy_artifact_0.zip"])
    httpserver.expect_request(
        f"/observatory/v2/episode-requests/{EPISODE_REQUEST_ID}/{MY_POLICY_VERSION_ID}/policy-artifact/0",
        method="GET",
        headers={"Authorization": "Bearer token"},
    ).respond_with_data(b"PK\x03\x04artifact zip", content_type="application/zip")

    result = CliRunner().invoke(
        app,
        [
            "episode-logs",
            EPISODE_REQUEST_ID,
            "--agent",
            "0",
            "--artifact",
            "--download-dir",
            str(tmp_path),
            "--server",
            httpserver.url_for(""),
        ],
    )

    assert result.exit_code == 0, result.output
    assert (tmp_path / f"{EPISODE_REQUEST_ID}-policy_agent_0.zip").read_bytes() == b"PK\x03\x04artifact zip"


def test_episode_logs_artifact_falls_back_to_job_level_when_v2_route_missing(
    httpserver: HTTPServer,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    episode_request = _episode_request(episode_request_id=EPISODE_REQUEST_ID, replay_url=None)
    del episode_request["assignments"]
    httpserver.expect_request(
        f"/observatory/v2/episode-requests/{EPISODE_REQUEST_ID}",
        method="GET",
    ).respond_with_json(episode_request)
    httpserver.expect_request(
        f"/observatory/jobs/{JOB_ID}/policy-artifact",
        method="GET",
    ).respond_with_json(["policy_artifact_0.zip"])
    # v2 ownership-scoped route is not deployed yet -> 404.
    httpserver.expect_request(
        f"/observatory/v2/episode-requests/{EPISODE_REQUEST_ID}/{MY_POLICY_VERSION_ID}/policy-artifact/0",
        method="GET",
    ).respond_with_data("not found", status=404)
    # Job-level route is deployed and serves the zip.
    httpserver.expect_request(
        f"/observatory/jobs/{JOB_ID}/policy-artifact/0",
        method="GET",
    ).respond_with_data(b"PK\x03\x04job-level zip", content_type="application/zip")

    result = CliRunner().invoke(
        app,
        [
            "episode-logs",
            EPISODE_REQUEST_ID,
            "--agent",
            "0",
            "--artifact",
            "--download-dir",
            str(tmp_path),
            "--server",
            httpserver.url_for(""),
        ],
    )

    assert result.exit_code == 0, result.output
    assert (tmp_path / f"{EPISODE_REQUEST_ID}-policy_agent_0.zip").read_bytes() == b"PK\x03\x04job-level zip"


def test_episode_logs_artifact_403_propagates_without_fallback(
    httpserver: HTTPServer,
    tmp_path: Path,
) -> None:
    episode_request = _episode_request(episode_request_id=EPISODE_REQUEST_ID, replay_url=None)
    del episode_request["assignments"]
    httpserver.expect_request(
        f"/observatory/v2/episode-requests/{EPISODE_REQUEST_ID}",
        method="GET",
    ).respond_with_json(episode_request)
    httpserver.expect_request(
        f"/observatory/jobs/{JOB_ID}/policy-artifact",
        method="GET",
    ).respond_with_json(["policy_artifact_0.zip"])
    httpserver.expect_request(
        f"/observatory/v2/episode-requests/{EPISODE_REQUEST_ID}/{MY_POLICY_VERSION_ID}/policy-artifact/0",
        method="GET",
    ).respond_with_data("denied", status=403)

    result = CliRunner().invoke(
        app,
        [
            "episode-logs",
            EPISODE_REQUEST_ID,
            "--agent",
            "0",
            "--artifact",
            "--download-dir",
            str(tmp_path),
            "--server",
            httpserver.url_for(""),
        ],
    )

    assert result.exit_code != 0
    assert "Access denied (403)" in str(result.exception) or "403" in result.output
    # No job-level fallback request should have been made on a genuine 403.
    assert not any(request.path == f"/observatory/jobs/{JOB_ID}/policy-artifact/0" for request, _ in httpserver.log)


def test_episode_logs_artifact_output_writes_named_file(
    httpserver: HTTPServer,
    tmp_path: Path,
) -> None:
    episode_request = _episode_request(episode_request_id=EPISODE_REQUEST_ID, replay_url=None)
    del episode_request["assignments"]
    httpserver.expect_request(
        f"/observatory/v2/episode-requests/{EPISODE_REQUEST_ID}",
        method="GET",
    ).respond_with_json(episode_request)
    httpserver.expect_request(
        f"/observatory/jobs/{JOB_ID}/policy-artifact",
        method="GET",
    ).respond_with_json(["policy_artifact_0.zip"])
    httpserver.expect_request(
        f"/observatory/v2/episode-requests/{EPISODE_REQUEST_ID}/{MY_POLICY_VERSION_ID}/policy-artifact/0",
        method="GET",
    ).respond_with_data(b"PK\x03\x04named zip", content_type="application/zip")

    output_path = tmp_path / "my-artifact.zip"
    result = CliRunner().invoke(
        app,
        [
            "episode-logs",
            EPISODE_REQUEST_ID,
            "--agent",
            "0",
            "--artifact",
            "--output",
            str(output_path),
            "--server",
            httpserver.url_for(""),
        ],
    )

    assert result.exit_code == 0, result.output
    assert output_path.read_bytes() == b"PK\x03\x04named zip"


def test_episode_logs_artifact_defaults_to_cwd_file(
    httpserver: HTTPServer,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    episode_request = _episode_request(episode_request_id=EPISODE_REQUEST_ID, replay_url=None)
    del episode_request["assignments"]
    httpserver.expect_request(
        f"/observatory/v2/episode-requests/{EPISODE_REQUEST_ID}",
        method="GET",
    ).respond_with_json(episode_request)
    httpserver.expect_request(
        f"/observatory/jobs/{JOB_ID}/policy-artifact",
        method="GET",
    ).respond_with_json(["policy_artifact_0.zip"])
    httpserver.expect_request(
        f"/observatory/v2/episode-requests/{EPISODE_REQUEST_ID}/{MY_POLICY_VERSION_ID}/policy-artifact/0",
        method="GET",
    ).respond_with_data(b"PK\x03\x04default zip", content_type="application/zip")

    result = CliRunner().invoke(
        app,
        [
            "episode-logs",
            EPISODE_REQUEST_ID,
            "--agent",
            "0",
            "--artifact",
            "--server",
            httpserver.url_for(""),
        ],
    )

    assert result.exit_code == 0, result.output
    default_path = tmp_path / f"{EPISODE_REQUEST_ID}-policy_agent_0.zip"
    assert default_path.read_bytes() == b"PK\x03\x04default zip"


def test_episode_logs_artifact_unknown_agent_lists_available(
    httpserver: HTTPServer,
    tmp_path: Path,
) -> None:
    episode_request = _episode_request(episode_request_id=EPISODE_REQUEST_ID, replay_url=None)
    del episode_request["assignments"]
    httpserver.expect_request(
        f"/observatory/v2/episode-requests/{EPISODE_REQUEST_ID}",
        method="GET",
    ).respond_with_json(episode_request)
    httpserver.expect_request(
        f"/observatory/jobs/{JOB_ID}/policy-artifact",
        method="GET",
    ).respond_with_json(["policy_artifact_0.zip"])

    result = CliRunner().invoke(
        app,
        [
            "episode-logs",
            EPISODE_REQUEST_ID,
            "--agent",
            "1",
            "--artifact",
            "--output",
            str(tmp_path / "x.zip"),
            "--server",
            httpserver.url_for(""),
        ],
    )

    assert result.exit_code != 0
    assert "Available agent indices: 0" in result.output


def test_replay_open_with_artifacts_downloads_zips(
    httpserver: HTTPServer,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    artifacts_dir = tmp_path / "artifacts"
    episode_request = _episode_request(episode_request_id=EPISODE_REQUEST_ID, replay_url=None)
    del episode_request["assignments"]
    httpserver.expect_request(
        f"/observatory/v2/episode-requests/{EPISODE_REQUEST_ID}",
        method="GET",
    ).respond_with_json(episode_request)
    httpserver.expect_request(
        f"/observatory/jobs/{JOB_ID}/policy-artifact",
        method="GET",
    ).respond_with_json(["policy_artifact_0.zip", "policy_artifact_1.zip"])
    # v2 route not deployed -> both fall back to the job-level route.
    httpserver.expect_request(
        f"/observatory/v2/episode-requests/{EPISODE_REQUEST_ID}/{MY_POLICY_VERSION_ID}/policy-artifact/0",
        method="GET",
    ).respond_with_data("not found", status=404)
    httpserver.expect_request(
        f"/observatory/v2/episode-requests/{EPISODE_REQUEST_ID}/{OTHER_POLICY_VERSION_ID}/policy-artifact/1",
        method="GET",
    ).respond_with_data("not found", status=404)
    httpserver.expect_request(
        f"/observatory/jobs/{JOB_ID}/policy-artifact/0",
        method="GET",
    ).respond_with_data(b"PK\x03\x04zip0", content_type="application/zip")
    httpserver.expect_request(
        f"/observatory/jobs/{JOB_ID}/policy-artifact/1",
        method="GET",
    ).respond_with_data(b"PK\x03\x04zip1", content_type="application/zip")

    result = CliRunner().invoke(
        app,
        [
            "replay-open",
            EPISODE_REQUEST_ID,
            "--with-artifacts",
            "--artifacts-dir",
            str(artifacts_dir),
            "--no-open-browser",
            "--server",
            httpserver.url_for(""),
        ],
    )

    # Artifacts are downloaded before the replay step; this episode has no replay_url, so the
    # replay step then exits, but the artifacts must already be on disk.
    assert "No replay URL is available" in result.output
    assert (artifacts_dir / "policy_artifact_0.zip").read_bytes() == b"PK\x03\x04zip0"
    assert (artifacts_dir / "policy_artifact_1.zip").read_bytes() == b"PK\x03\x04zip1"


def test_replay_open_downloads_only_game_image_for_local_replay(
    httpserver: HTTPServer,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    replay_path = tmp_path / "replay"
    replay_path.write_text('{"frames":[]}\n')
    opened_urls: list[str] = []
    httpserver.expect_request(
        f"/observatory/v2/episode-requests/{EPISODE_REQUEST_ID}",
        method="GET",
        headers={"Authorization": "Bearer token"},
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
    monkeypatch.setattr("coworld.tournament_cli.webbrowser.open", opened_urls.append)

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
    assert opened_urls == ["http://replay.local"]


def test_replay_open_hosted_opens_viewer_url(httpserver: HTTPServer, monkeypatch: pytest.MonkeyPatch) -> None:
    opened_urls: list[str] = []
    replay_url = "https://storage.example/replay.z"
    viewer_url = "https://softmax.example/observatory/coworld-replays/session"
    httpserver.expect_request(
        f"/observatory/v2/episode-requests/{EPISODE_REQUEST_ID}",
        method="GET",
        headers={"Authorization": "Bearer token"},
    ).respond_with_json(_episode_request(episode_request_id=EPISODE_REQUEST_ID, replay_url=replay_url))
    httpserver.expect_request(
        "/observatory/v2/coworlds/replays/session",
        method="POST",
        headers={"Authorization": "Bearer token"},
    ).respond_with_json({"viewer_url": viewer_url})
    monkeypatch.setattr("coworld.tournament_cli.webbrowser.open", opened_urls.append)

    result = CliRunner().invoke(
        app,
        [
            "replay-open",
            EPISODE_REQUEST_ID,
            "--hosted",
            "--server",
            httpserver.url_for(""),
        ],
    )

    assert result.exit_code == 0, result.output
    assert viewer_url in result.output
    assert opened_urls == [viewer_url]


def _expect_mine_memberships(httpserver: HTTPServer, *, division_id: str | None = DIVISION_ID) -> None:
    httpserver.expect_request(
        "/observatory/v2/league-policy-memberships",
        method="GET",
        headers={"Authorization": "Bearer token"},
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


def _membership(
    *,
    division_id: str = DIVISION_ID,
    status: str = "competing",
    substatus: str | None = None,
    end_time: str | None = None,
) -> dict[str, object]:
    return {
        "id": "lpm_00000000-0000-0000-0000-000000000051",
        "status": status,
        "substatus": substatus,
        "start_time": NOW,
        "end_time": end_time,
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
        "round_id": ROUND_ID,
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
