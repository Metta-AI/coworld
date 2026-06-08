import json

import pytest
from pytest_httpserver import HTTPServer
from typer.testing import CliRunner
from werkzeug import Request, Response

from coworld.cli import app

NOW = "2026-05-12T12:00:00Z"
COWORLD_ID = "cow_00000000-0000-0000-0000-000000000015"
XP_REQUEST_ID = "xreq_00000000-0000-0000-0000-000000000080"
EPISODE_REQUEST_ID = "ereq_00000000-0000-0000-0000-000000000016"
POLICY_VERSION_ID = "00000000-0000-0000-0000-000000000031"
POLICY_ID = "00000000-0000-0000-0000-000000000032"


@pytest.fixture(autouse=True)
def _fake_softmax_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("softmax.auth.load_current_token", lambda *, server: "token")


def _episode_request() -> dict[str, object]:
    return {
        "id": EPISODE_REQUEST_ID,
        "requester_user_id": "user_00000000-0000-0000-0000-000000000071",
        "coworld_id": COWORLD_ID,
        "status": "pending",
        "policy_version_ids": [POLICY_VERSION_ID],
        "participants": [
            {
                "position": 0,
                "policy_version_id": POLICY_VERSION_ID,
                "policy_id": POLICY_ID,
                "policy_name": "paintbot",
                "version": 3,
                "player_id": "player_00000000-0000-0000-0000-000000000061",
                "player_name": "Me",
            },
        ],
        "scores": [],
        "created_at": NOW,
    }


def _experience_request_row() -> dict[str, object]:
    return {
        "id": XP_REQUEST_ID,
        "requester_user_id": "user_00000000-0000-0000-0000-000000000071",
        "requester": "me@example.com",
        "coworld_id": COWORLD_ID,
        "coworld_name": "paintarena",
        "coworld_version": "0.1.0",
        "variant_id": "default",
        "status": "pending",
        "episode_count": 1,
        "pending_count": 1,
        "submitted_count": 0,
        "running_count": 0,
        "completed_count": 0,
        "failed_count": 0,
        "error": None,
        "created_at": NOW,
        "started_at": None,
        "completed_at": None,
    }


def _experience_request_detail() -> dict[str, object]:
    return {**_experience_request_row(), "episodes": [_episode_request()]}


def test_xp_request_create_posts_body_and_prints_id(httpserver: HTTPServer) -> None:
    captured: dict[str, object] = {}

    def handler(request: Request) -> Response:
        captured["body"] = json.loads(request.get_data())
        captured["auth"] = request.headers.get("Authorization")
        return Response(json.dumps(_experience_request_detail()), content_type="application/json")

    httpserver.expect_request("/observatory/v2/experience-requests", method="POST").respond_with_handler(handler)

    body = {"coworld_id": COWORLD_ID, "policy_version_ids": [POLICY_VERSION_ID], "num_episodes": 1}
    result = CliRunner().invoke(
        app,
        ["xp-request", "create", "-", "--server", httpserver.url_for("/")],
        input=json.dumps(body),
    )

    assert result.exit_code == 0, result.output
    assert captured["body"] == body
    assert captured["auth"] == "Bearer token"
    assert XP_REQUEST_ID in result.output


def test_xp_request_create_reads_file(httpserver: HTTPServer, tmp_path) -> None:
    httpserver.expect_request("/observatory/v2/experience-requests", method="POST").respond_with_json(
        _experience_request_detail()
    )
    body_path = tmp_path / "body.json"
    body_path.write_text(json.dumps({"coworld_id": COWORLD_ID, "policy_version_ids": [POLICY_VERSION_ID]}))

    result = CliRunner().invoke(
        app,
        ["xp-request", "create", str(body_path), "--server", httpserver.url_for("/")],
    )

    assert result.exit_code == 0, result.output
    assert XP_REQUEST_ID in result.output


def test_xp_request_list_renders_rows(httpserver: HTTPServer) -> None:
    httpserver.expect_request(
        "/observatory/v2/experience-requests",
        method="GET",
        query_string={"mine": "true", "limit": "50", "offset": "0"},
    ).respond_with_json({"entries": [_experience_request_row()], "total_count": 1, "limit": 50, "offset": 0})

    result = CliRunner().invoke(
        app, ["xp-request", "list", "--mine", "--server", httpserver.url_for("/")], env={"COLUMNS": "200"}
    )

    assert result.exit_code == 0, result.output
    assert XP_REQUEST_ID in result.output
    assert "paintarena:0.1.0" in result.output


def test_xp_request_list_json(httpserver: HTTPServer) -> None:
    httpserver.expect_request("/observatory/v2/experience-requests", method="GET").respond_with_json(
        {"entries": [_experience_request_row()], "total_count": 1, "limit": 50, "offset": 0}
    )

    result = CliRunner().invoke(app, ["xp-request", "list", "--json", "--server", httpserver.url_for("/")])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["entries"][0]["id"] == XP_REQUEST_ID


def test_xp_request_get_renders_detail_and_episodes(httpserver: HTTPServer) -> None:
    httpserver.expect_request(f"/observatory/v2/experience-requests/{XP_REQUEST_ID}", method="GET").respond_with_json(
        _experience_request_detail()
    )

    result = CliRunner().invoke(
        app, ["xp-request", "get", XP_REQUEST_ID, "--server", httpserver.url_for("/")], env={"COLUMNS": "200"}
    )

    assert result.exit_code == 0, result.output
    assert XP_REQUEST_ID in result.output
    assert EPISODE_REQUEST_ID in result.output


def test_xp_request_episodes_renders_children(httpserver: HTTPServer) -> None:
    httpserver.expect_request(
        f"/observatory/v2/experience-requests/{XP_REQUEST_ID}/episodes", method="GET"
    ).respond_with_json([_episode_request()])

    result = CliRunner().invoke(
        app, ["xp-request", "episodes", XP_REQUEST_ID, "--server", httpserver.url_for("/")], env={"COLUMNS": "200"}
    )

    assert result.exit_code == 0, result.output
    assert EPISODE_REQUEST_ID in result.output
