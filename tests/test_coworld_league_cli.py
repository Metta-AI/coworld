import pytest
from pytest_httpserver import HTTPServer
from typer.testing import CliRunner

from coworld.cli import app

SEED_RESPONSE = {
    "id": "lseed_00000000-0000-0000-0000-000000000071",
    "coworld_name": "newworld",
    "template": "commissioner_driven",
    "overrides": {"is_game_of_week": True, "commissioner_runnable_id": "cue-n-woo-commissioner"},
    "enabled": True,
    "created_by": "debug_user_id",
    "notes": None,
    "created_at": "2026-06-05T12:00:00Z",
    "league_id": "league_00000000-0000-0000-0000-000000000081",
}


@pytest.fixture(autouse=True)
def _fake_softmax_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("softmax.auth.load_current_token", lambda *, server: "token")


def test_create_coworld_league_seed_posts_request(httpserver: HTTPServer) -> None:
    httpserver.expect_request(
        "/observatory/v2/coworld-league-seeds",
        method="POST",
        headers={"Authorization": "Bearer token"},
        json={
            "coworld_name": "newworld",
            "template": "commissioner_driven",
            "overrides": {"is_game_of_week": True, "commissioner_runnable_id": "cue-n-woo-commissioner"},
            "enabled": True,
        },
    ).respond_with_json(SEED_RESPONSE)

    result = CliRunner().invoke(
        app,
        [
            "league",
            "create",
            "newworld",
            "--set",
            "is_game_of_week=true",
            "--set",
            "commissioner_runnable_id=cue-n-woo-commissioner",
            "--server",
            httpserver.url_for(""),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "newworld" in result.output
    assert "league_00000000-0000-0000-0000-000000000081" in result.output


def test_create_coworld_league_seed_without_overrides_posts_no_commissioner_override(httpserver: HTTPServer) -> None:
    seed_response = {**SEED_RESPONSE, "overrides": None}
    httpserver.expect_request(
        "/observatory/v2/coworld-league-seeds",
        method="POST",
        headers={"Authorization": "Bearer token"},
        json={
            "coworld_name": "newworld",
            "template": "commissioner_driven",
            "overrides": None,
            "enabled": True,
        },
    ).respond_with_json(seed_response)

    result = CliRunner().invoke(
        app,
        [
            "league",
            "create",
            "newworld",
            "--server",
            httpserver.url_for(""),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "newworld" in result.output


def test_create_coworld_league_seed_rejects_bad_override() -> None:
    result = CliRunner().invoke(
        app,
        [
            "league",
            "create",
            "newworld",
            "--template",
            "default",
            "--set",
            "missing-equals",
            "--server",
            "https://softmax.test/api",
        ],
    )

    assert result.exit_code == 2
    assert "KEY=VALUE" in result.output


def test_list_coworld_league_seeds(httpserver: HTTPServer) -> None:
    httpserver.expect_request(
        "/observatory/v2/coworld-league-seeds",
        method="GET",
        headers={"Authorization": "Bearer token"},
    ).respond_with_json([SEED_RESPONSE])

    result = CliRunner().invoke(
        app,
        ["league", "list", "--server", httpserver.url_for("")],
    )

    assert result.exit_code == 0, result.output
    assert "newworld" in result.output
    assert "commissioner_driven" in result.output


def test_update_coworld_league_seed_replaces_overrides(httpserver: HTTPServer) -> None:
    response = {
        **SEED_RESPONSE,
        "overrides": {
            "commissioner_config_extensions": {
                "persistent_game_config_overlay_secret": "persistent_realm",
            },
            "commissioner_config_overlay_secret": "persistent_window_feed",
        },
    }
    httpserver.expect_request(
        "/observatory/v2/coworld-league-seeds/newworld",
        method="PATCH",
        headers={"Authorization": "Bearer token"},
        json={"overrides": response["overrides"]},
    ).respond_with_json(response)

    result = CliRunner().invoke(
        app,
        [
            "league",
            "update",
            "newworld",
            "--set",
            'commissioner_config_extensions={"persistent_game_config_overlay_secret":"persistent_realm"}',
            "--set",
            "commissioner_config_overlay_secret=persistent_window_feed",
            "--server",
            httpserver.url_for(""),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Updated league seed" in result.output
    assert "league_00000000-0000-0000-0000-000000000081" in result.output


def test_update_coworld_league_seed_requires_overrides() -> None:
    result = CliRunner().invoke(app, ["league", "update", "newworld"])

    assert result.exit_code == 2
    assert "At least one --set" in result.output
