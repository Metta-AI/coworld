import pytest
from pytest_httpserver import HTTPServer
from typer.testing import CliRunner

from coworld.cli import app

POLICY_VERSION_ID = "00000000-0000-0000-0000-000000000031"
POLICY_ID = "00000000-0000-0000-0000-000000000032"
LEAGUE_ID = "league_00000000-0000-0000-0000-000000000041"


@pytest.fixture(autouse=True)
def _fake_softmax_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("softmax.auth.load_current_token", lambda *, server: "token")
    monkeypatch.setattr("softmax.auth.load_user_token", lambda *, server: "token")


def test_submit_policy_to_league_posts_v2_submission(
    httpserver: HTTPServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened: list[str] = []
    monkeypatch.setattr("softmax.auth.load_current_token", lambda *, server: "player-token")
    monkeypatch.setattr("softmax.auth.load_user_token", lambda *, server: pytest.fail("used user token"))
    monkeypatch.setattr("coworld.submit.webbrowser.open", lambda url: opened.append(url) or True)
    _expect_policy_versions(httpserver, [_policy_version(version=3)], token="player-token")
    httpserver.expect_request(
        "/observatory/v2/league-submissions",
        method="POST",
        headers={"Authorization": "Bearer player-token"},
        json={
            "league_id": LEAGUE_ID,
            "policy_version_id": POLICY_VERSION_ID,
            "auto_champion": "always",
            "preferences": {"team_name": "Dungeon Delvers", "role": "tank", "priority": 1},
        },
    ).respond_with_json(
        _submission(
            id="sub_00000000-0000-0000-0000-000000000051",
            status="placed",
            membership_id="lpm_00000000-0000-0000-0000-000000000061",
        )
    )

    result = CliRunner().invoke(
        app,
        [
            "submit",
            "paintbot:v3",
            "--league",
            LEAGUE_ID,
            "--server",
            httpserver.url_for(""),
            "--preference",
            "team_name=Dungeon Delvers",
            "--preference",
            "role=tank",
            "--preference",
            "priority=1",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Submitted to league" in result.output
    assert LEAGUE_ID in result.output
    assert "Status:" in result.output
    assert "placed" in result.output
    assert "lpm_00000000-0000-0000-0000-000000000061" in result.output
    policy_path = f"/observatory/policies/versions/{POLICY_VERSION_ID}"
    assert policy_path in result.output
    assert "https://softmax.com/docs/coworld/build-a-player/submit-to-a-league" in result.output
    assert "League forum: https://softmax.com/api/observatory/v2/forums/Paint Arena.md" in result.output
    assert "League wiki: https://softmax.com/api/observatory/v2/wikis/Paint Arena/pages.md" in result.output
    assert opened == [policy_path]
    policy_query = next(
        request for request, _ in httpserver.log if request.path == "/observatory/stats/policy-versions"
    )
    assert policy_query.args["name_exact"] == "paintbot"
    assert policy_query.args["version"] == "3"
    assert not any(request.path == "/observatory/v2/leagues" for request, _ in httpserver.log)


def test_submit_policy_rejects_malformed_preference() -> None:
    result = CliRunner().invoke(
        app,
        [
            "submit",
            "paintbot",
            "--league",
            LEAGUE_ID,
            "--preference",
            "role",
        ],
    )

    assert result.exit_code == 2
    assert "Expected KEY=VALUE format" in result.output


def test_submit_policy_can_disable_auto_champion(
    httpserver: HTTPServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("coworld.submit.webbrowser.open", lambda url: True)
    _expect_policy_versions(httpserver, [_policy_version(version=3)])
    httpserver.expect_request(
        "/observatory/v2/league-submissions",
        method="POST",
        headers={"Authorization": "Bearer token"},
        json={"league_id": LEAGUE_ID, "policy_version_id": POLICY_VERSION_ID, "auto_champion": "never"},
    ).respond_with_json(_submission(status="placed"))

    result = CliRunner().invoke(
        app,
        [
            "submit",
            "paintbot:v3",
            "--league",
            LEAGUE_ID,
            "--server",
            httpserver.url_for(""),
            "--auto-champion",
            "never",
            "--no-open-browser",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Auto champion:" in result.output
    assert "never" in result.output


def test_submit_policy_can_request_lineage_auto_champion(
    httpserver: HTTPServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("coworld.submit.webbrowser.open", lambda url: True)
    _expect_policy_versions(httpserver, [_policy_version(version=3)])
    httpserver.expect_request(
        "/observatory/v2/league-submissions",
        method="POST",
        headers={"Authorization": "Bearer token"},
        json={"league_id": LEAGUE_ID, "policy_version_id": POLICY_VERSION_ID, "auto_champion": "lineage"},
    ).respond_with_json(_submission(status="placed"))

    result = CliRunner().invoke(
        app,
        [
            "submit",
            "paintbot:v3",
            "--league",
            LEAGUE_ID,
            "--server",
            httpserver.url_for(""),
            "--auto-champion",
            "lineage",
            "--no-open-browser",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Auto champion:" in result.output
    assert "lineage" in result.output


def test_submit_policy_no_open_browser_skips_launch(
    httpserver: HTTPServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened: list[str] = []
    monkeypatch.setattr("coworld.submit.webbrowser.open", lambda url: opened.append(url) or True)
    _expect_policy_versions(httpserver, [_policy_version(version=3)])
    httpserver.expect_request(
        "/observatory/v2/league-submissions",
        method="POST",
    ).respond_with_json(_submission(status="placed"))

    result = CliRunner().invoke(
        app,
        [
            "submit",
            "paintbot:v3",
            "--league",
            LEAGUE_ID,
            "--server",
            httpserver.url_for(""),
            "--no-open-browser",
        ],
    )

    assert result.exit_code == 0, result.output
    assert f"/observatory/policies/versions/{POLICY_VERSION_ID}" in result.output
    assert opened == []


def test_submit_policy_pending_submission_opens_status_page(
    httpserver: HTTPServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened: list[str] = []
    monkeypatch.setattr("coworld.submit.webbrowser.open", lambda url: opened.append(url) or True)
    _expect_policy_versions(httpserver, [_policy_version(version=3)])
    httpserver.expect_request(
        "/observatory/v2/league-submissions",
        method="POST",
    ).respond_with_json(_submission(status="pending"))

    result = CliRunner().invoke(
        app,
        [
            "submit",
            "paintbot:v3",
            "--league",
            LEAGUE_ID,
            "--server",
            httpserver.url_for(""),
        ],
    )

    assert result.exit_code == 0, result.output
    status_path = f"/observatory/v2?tab=uploads&detail=policy-version:{POLICY_VERSION_ID}"
    assert status_path in result.output
    assert "Status page:" in result.output
    assert opened == [status_path]


def test_submit_policy_requires_league_id_option() -> None:
    result = CliRunner().invoke(
        app,
        [
            "submit",
            "paintbot",
            "--server",
            "https://softmax.test/api",
        ],
    )

    assert result.exit_code == 2
    assert "Missing option" in result.output
    assert "league" in result.output.lower()


def test_submit_policy_reports_missing_policy_without_posting_submission(
    httpserver: HTTPServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _expect_policy_versions(httpserver, [])

    result = CliRunner().invoke(
        app,
        [
            "submit",
            "missing-policy",
            "--league",
            LEAGUE_ID,
            "--server",
            httpserver.url_for(""),
        ],
    )

    assert result.exit_code == 1
    assert "Policy 'missing-policy' not found" in result.output
    assert not any(request.path == "/observatory/v2/league-submissions" for request, _ in httpserver.log)


def _expect_policy_versions(
    httpserver: HTTPServer,
    entries: list[dict[str, object]],
    *,
    token: str = "token",
) -> None:
    httpserver.expect_request(
        "/observatory/stats/policy-versions",
        method="GET",
        headers={"Authorization": f"Bearer {token}"},
    ).respond_with_json({"entries": entries, "next_cursor": None})


def _policy_version(*, version: int) -> dict[str, object]:
    return {
        "id": POLICY_VERSION_ID,
        "policy_id": POLICY_ID,
        "name": "paintbot",
        "version": version,
        "created_at": "2026-05-11T12:00:00Z",
        "policy_created_at": "2026-05-11T11:00:00Z",
        "user_id": "debug_user_id",
        "tags": {},
        "attributes": {"kind": "docker-img"},
    }


def _submission(
    *,
    status: str,
    id: str = "sub_1",
    membership_id: str | None = None,
) -> dict[str, object]:
    return {
        "id": id,
        "status": status,
        "league": {
            "id": LEAGUE_ID,
            "name": "Paint Arena",
            "game": {
                "id": "game_1",
                "name": "Paint Arena",
                "created_at": "2026-05-11T10:00:00Z",
            },
            "created_at": "2026-05-11T10:00:00Z",
            "participation_url": f"https://softmax.com/api/observatory/v2/leagues/{LEAGUE_ID}.md",
            "forum_markdown_url": "https://softmax.com/api/observatory/v2/forums/Paint Arena.md",
            "wiki_markdown_url": "https://softmax.com/api/observatory/v2/wikis/Paint Arena/pages.md",
        },
        "policy_version": {
            "id": POLICY_VERSION_ID,
            "policy": {"id": POLICY_ID, "name": "paintbot"},
            "version": 3,
        },
        "league_policy_membership_id": membership_id,
        "created_at": "2026-05-11T12:00:00Z",
    }


def test_http_failures_print_an_actionable_error_instead_of_a_traceback(httpserver: HTTPServer) -> None:
    httpserver.expect_request("/observatory/v2/coworlds/cow_missing", method="GET").respond_with_json(
        {"detail": "Coworld not found"}, status=422, headers={"X-Request-Id": "req-download-1"}
    )

    result = CliRunner().invoke(app, ["download", "cow_missing", "--server", httpserver.url_for("")])

    assert result.exit_code == 1, result.output
    assert "Traceback" not in result.output
    assert "returned HTTP 422" in result.output
    assert "Detail: Coworld not found" in result.output
    assert "Request id: req-download-1" in result.output
    assert "Docs: https://softmax.com/docs/api-reference/error-handling" in result.output


def test_api_client_failures_render_their_hint_without_a_traceback(httpserver: HTTPServer) -> None:
    httpserver.expect_request(f"/observatory/v2/leagues/{LEAGUE_ID}", method="GET").respond_with_json(
        {"detail": "Failed to authenticate"}, status=401, headers={"X-Request-Id": "req-league-1"}
    )

    result = CliRunner().invoke(app, ["leagues", LEAGUE_ID, "--server", httpserver.url_for("")])

    assert result.exit_code == 1, result.output
    assert "Traceback" not in result.output
    assert "Authentication failed (401)" in result.output
    assert "uv run softmax login" in result.output
    assert "Request id: req-league-1" in result.output
    assert "Docs: https://softmax.com/docs/guides/authentication" in result.output


def test_guidance_failure_precedes_remote_request(tmp_path, httpserver, monkeypatch):
    monkeypatch.delenv("COWORLD_AGENT_GUIDANCE", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("coworld.agent_guidance.detect_coding_agent", lambda: "codex")
    monkeypatch.delenv("COWORLD_AGENT_GUIDANCE", raising=False)
    (tmp_path / ".coworld-project").write_text("player")
    (tmp_path / "AGENTS.md").write_text("<!-- BEGIN:coworld-agent-rules -->")
    result = CliRunner().invoke(
        app, ["submit", "policy:v1", "--league", "league_x"] + ["--server", httpserver.url_for("")]
    )
    assert "Malformed" in result.output
    assert result.exit_code == 1
    assert httpserver.log == []
