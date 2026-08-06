import json
from pathlib import Path

import pytest
from pytest_httpserver import HTTPServer
from typer.testing import CliRunner

from coworld.cli import app

SEED_RESPONSE = {
    "id": "lseed_00000000-0000-0000-0000-000000000071",
    "coworld_name": "newworld",
    "league_key": "arena",
    "league_name": "New World Arena",
    "default_variant_id": "arena-2v2",
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
            "league_key": "arena",
            "league_name": "New World Arena",
            "default_variant_id": "arena-2v2",
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
            "arena",
            "New World Arena",
            "--default-variant",
            "arena-2v2",
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
            "league_key": "arena",
            "league_name": "New World Arena",
            "default_variant_id": "arena-2v2",
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
            "arena",
            "New World Arena",
            "--default-variant",
            "arena-2v2",
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
            "arena",
            "New World Arena",
            "--default-variant",
            "arena-2v2",
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
    assert SEED_RESPONSE["id"] in result.output
    assert "newworld" in result.output
    assert "arena" in result.output


def test_rebind_coworld_league_seeds_is_dry_run_by_default(httpserver: HTTPServer, tmp_path: Path) -> None:
    seed_id = SEED_RESPONSE["id"]
    plan = tmp_path / "rebind.json"
    binding = {
        "coworld_name": "newworld",
        "league_key": "arena",
        "default_variant_id": "arena-2v2",
        "effective_variant_id": "arena-2v2",
    }
    change = {
        "coworld_name": binding["coworld_name"],
        "league_key": binding["league_key"],
    }
    plan.write_text(
        json.dumps({"changes": [{"seed_id": seed_id, **change}]}),
        encoding="utf-8",
    )
    httpserver.expect_request(
        "/observatory/v2/coworld-league-seeds/rebind",
        method="POST",
        headers={"Authorization": "Bearer token"},
        json={"dry_run": True, "changes": [{"seed_id": seed_id, **change}]},
    ).respond_with_json(
        {
            "dry_run": True,
            "applied": False,
            "results": [
                {
                    "seed_id": seed_id,
                    "league_id": None,
                    "league_name": "New World Arena",
                    "current": binding,
                    "proposed": binding,
                    "commissioner_key": "platform",
                    "canonical_coworld_id": "cow_00000000-0000-0000-0000-000000000001",
                    "counts": {"divisions": 0, "memberships": 0, "submissions": 0, "active_rounds": 0},
                    "blocking_reasons": [],
                }
            ],
        }
    )

    result = CliRunner().invoke(app, ["league", "rebind", str(plan), "--server", httpserver.url_for("")])

    assert result.exit_code == 0, result.output
    assert "Dry run complete" in result.output
    assert "ready" in result.output


def test_set_coworld_game_of_week_uses_dedicated_route(httpserver: HTTPServer) -> None:
    httpserver.expect_request(
        "/observatory/v2/coworld-league-seeds/lseed_00000000-0000-0000-0000-000000000071/game-of-week",
        method="PUT",
        headers={"Authorization": "Bearer token"},
    ).respond_with_json(SEED_RESPONSE)

    result = CliRunner().invoke(
        app,
        [
            "league",
            "game-of-week",
            "lseed_00000000-0000-0000-0000-000000000071",
            "--server",
            httpserver.url_for(""),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Game of the week is now New World Arena" in result.output


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
        "/observatory/v2/coworld-league-seeds/lseed_00000000-0000-0000-0000-000000000071",
        method="PATCH",
        headers={"Authorization": "Bearer token"},
        json={"overrides": response["overrides"]},
    ).respond_with_json(response)

    result = CliRunner().invoke(
        app,
        [
            "league",
            "update",
            "lseed_00000000-0000-0000-0000-000000000071",
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
    result = CliRunner().invoke(
        app,
        ["league", "update", "lseed_00000000-0000-0000-0000-000000000071"],
    )

    assert result.exit_code == 2
    assert "Provide --set, --default-variant, or --use-manifest-default" in result.output
