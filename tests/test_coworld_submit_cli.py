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


def test_submit_policy_to_league_posts_v2_submission(
    httpserver: HTTPServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened: list[str] = []
    monkeypatch.setattr("coworld.submit.webbrowser.open", lambda url: opened.append(url) or True)
    _expect_policy_versions(httpserver, [_policy_version(version=3)])
    httpserver.expect_request(
        "/observatory/v2/league-submissions",
        method="POST",
        headers={"Authorization": "Bearer token"},
        json={"league_id": LEAGUE_ID, "policy_version_id": POLICY_VERSION_ID},
    ).respond_with_json(
        {
            "id": "sub_00000000-0000-0000-0000-000000000051",
            "status": "placed",
            "league_policy_membership_id": "lpm_00000000-0000-0000-0000-000000000061",
        }
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
    assert opened == [policy_path]
    policy_query = next(
        request for request, _ in httpserver.log if request.path == "/observatory/stats/policy-versions"
    )
    assert policy_query.args["name_exact"] == "paintbot"
    assert policy_query.args["version"] == "3"
    assert not any(request.path == "/observatory/v2/leagues" for request, _ in httpserver.log)


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
    ).respond_with_json({"id": "sub_1", "status": "placed"})

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


def _expect_policy_versions(httpserver: HTTPServer, entries: list[dict[str, object]]) -> None:
    httpserver.expect_request(
        "/observatory/stats/policy-versions",
        method="GET",
        headers={"Authorization": "Bearer token"},
    ).respond_with_json({"entries": entries, "total_count": len(entries)})


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
