import json
from pathlib import Path

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
    monkeypatch.setattr("softmax_client.credentials.load_current_token", lambda *, server: "token")


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
                "kind": "policy",
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


def _closed_round(round_id: str, number: int) -> dict[str, object]:
    return {
        "league_id": "league_1",
        "league_name": "Paint League",
        "round_id": round_id,
        "round_number": number,
        "closed_at": f"2026-10-{number:02d}T12:00:00Z",
    }


def test_xp_request_help_documents_request_shapes() -> None:
    result = CliRunner().invoke(app, ["xp-request", "--help"], env={"COLUMNS": "200"})

    assert result.exit_code == 0, result.output
    assert "Create and inspect hosted Experience Requests" in result.output
    assert "uv run coworld xp-request create xp-request-candidate.json" in result.output
    assert "target.league_id" in result.output
    assert "policy_ref/top_n/random" in result.output
    assert "slot assignments" in result.output
    assert "coworld_id, roster, and num_episodes" in result.output
    assert "Compare the previous best and candidate" in result.output
    assert "--title" in result.output
    assert "--description" in result.output


def test_xp_request_create_posts_body_and_prints_id(httpserver: HTTPServer) -> None:
    captured: dict[str, object] = {}

    def handler(request: Request) -> Response:
        captured["body"] = json.loads(request.get_data())
        captured["auth"] = request.headers.get("Authorization")
        return Response(json.dumps(_experience_request_detail()), content_type="application/json")

    httpserver.expect_request("/observatory/v2/experience-requests", method="POST").respond_with_handler(handler)

    body = {
        "coworld_id": COWORLD_ID,
        "roster": [{"player": {"policy_ref": POLICY_VERSION_ID}, "slot": 0}],
        "num_episodes": 1,
    }
    result = CliRunner().invoke(
        app,
        ["xp-request", "create", "-", "--server", httpserver.url_for("/")],
        input=json.dumps(body),
    )

    assert result.exit_code == 0, result.output
    assert captured["body"] == body
    assert captured["auth"] == "Bearer token"
    assert XP_REQUEST_ID in result.output


def test_xp_request_create_merges_title_and_description_into_body(httpserver: HTTPServer) -> None:
    captured: dict[str, object] = {}

    def handler(request: Request) -> Response:
        captured["body"] = json.loads(request.get_data())
        return Response(
            json.dumps({**_experience_request_detail(), "title": "Wider radius", "description": "Expect more wins."}),
            content_type="application/json",
        )

    httpserver.expect_request("/observatory/v2/experience-requests", method="POST").respond_with_handler(handler)

    body = {"coworld_id": COWORLD_ID, "roster": [{"player": {"policy_ref": POLICY_VERSION_ID}, "slot": 0}]}
    result = CliRunner().invoke(
        app,
        [
            "xp-request",
            "create",
            "-",
            "--title",
            "Wider radius",
            "--description",
            "Expect more wins.",
            "--server",
            httpserver.url_for("/"),
        ],
        input=json.dumps(body),
    )

    assert result.exit_code == 0, result.output
    assert captured["body"] == {**body, "title": "Wider radius", "description": "Expect more wins."}
    assert "Title: Wider radius" in result.output
    assert "Description: Expect more wins." in result.output


def test_xp_request_create_reads_file(httpserver: HTTPServer, tmp_path) -> None:
    httpserver.expect_request("/observatory/v2/experience-requests", method="POST").respond_with_json(
        _experience_request_detail()
    )
    body_path = tmp_path / "body.json"
    body_path.write_text(
        json.dumps(
            {
                "coworld_id": COWORLD_ID,
                "roster": [{"player": {"policy_ref": POLICY_VERSION_ID}, "slot": 0}],
            }
        )
    )

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
        query_string={"mine": "true", "limit": "50"},
    ).respond_with_json({"entries": [_experience_request_row()], "next_cursor": None})

    result = CliRunner().invoke(
        app, ["xp-request", "list", "--mine", "--server", httpserver.url_for("/")], env={"COLUMNS": "200"}
    )

    assert result.exit_code == 0, result.output
    assert XP_REQUEST_ID in result.output
    assert "paintarena:0.1.0" in result.output


def test_xp_request_list_json(httpserver: HTTPServer) -> None:
    httpserver.expect_request("/observatory/v2/experience-requests", method="GET").respond_with_json(
        {"entries": [_experience_request_row()], "next_cursor": "page-2"}
    )

    result = CliRunner().invoke(app, ["xp-request", "list", "--json", "--server", httpserver.url_for("/")])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["entries"][0]["id"] == XP_REQUEST_ID
    assert payload["next_cursor"] == "page-2"


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
    assert not any(request.path.endswith("/feed-posts/check") for request, _ in httpserver.log)


def test_xp_request_get_completed_ends_with_feed_reminder(
    httpserver: HTTPServer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    detail = {**_experience_request_detail(), "status": "completed", "completed_at": NOW}
    httpserver.expect_request(f"/observatory/v2/experience-requests/{XP_REQUEST_ID}", method="GET").respond_with_json(
        detail
    )
    checks = [
        {"human_name": "Pawel", "rounds": [_closed_round("round_1", 1)], "sensei_due": None},
        {"human_name": "Pawel", "rounds": [_closed_round("round_2", 2)], "sensei_due": None},
    ]
    httpserver.expect_request(
        "/observatory/v2/coworlds/paintarena/feed-posts/check", method="GET"
    ).respond_with_handler(lambda request: Response(json.dumps(checks.pop(0)), content_type="application/json"))
    args = ["xp-request", "get", XP_REQUEST_ID, "--server", httpserver.url_for("/")]

    first = CliRunner().invoke(app, args, env={"COLUMNS": "200"})
    second = CliRunner().invoke(app, args, env={"COLUMNS": "200"})

    assert first.exit_code == 0, first.output
    assert "Feed for" not in first.output
    assert second.exit_code == 0, second.output
    assert second.output.rstrip().endswith(
        "Feed for Pawel: lesson due? uv run coworld feed hat sensei --coworld 'paintarena' · "
        "urgent? uv run coworld feed hat roger"
    )


def test_xp_request_episodes_renders_children(httpserver: HTTPServer) -> None:
    httpserver.expect_request("/observatory/v2/episode-requests", method="GET").respond_with_json(
        {
            "entries": [
                {
                    "id": EPISODE_REQUEST_ID,
                    "experience_request_id": XP_REQUEST_ID,
                    "created_at": NOW,
                    "status": "pending",
                    "error_type": None,
                    "evidence_state": "pending",
                }
            ],
            "unavailable_ids": [],
            "next_cursor": None,
            "observed_at": NOW,
        }
    )

    result = CliRunner().invoke(
        app, ["xp-request", "episodes", XP_REQUEST_ID, "--server", httpserver.url_for("/")], env={"COLUMNS": "200"}
    )

    assert result.exit_code == 0, result.output
    assert EPISODE_REQUEST_ID in result.output
