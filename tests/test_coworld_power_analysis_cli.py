from __future__ import annotations

import json

import pytest
from pytest_httpserver import HTTPServer
from typer.testing import CliRunner
from werkzeug.wrappers import Request, Response

from coworld.cli import app

DIVISION_ID = "div_00000000-0000-0000-0000-000000000001"
OTHER_DIVISION_ID = "div_00000000-0000-0000-0000-000000000002"
LEAGUE_ID = "league_00000000-0000-0000-0000-000000000003"


@pytest.fixture(autouse=True)
def _token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("softmax.auth.load_current_token", lambda *, server: "token")


def _report() -> dict:
    mode = {
        "episodes_used": 40,
        "ally_episodes_excluded": 2,
        "episodes_dropped_unclean": 1,
        "wins": 20,
        "ties_mutual_loss": 0,
        "ties_zero": 0,
        "losses": 20,
        "operating_point": 0.5,
        "score_variance": 0.25,
        "pairs_detected": 0,
        "pair_correlation": 0.0,
        "design_effect": 1.0,
        "aleatoric": None,
        "flags": ["low_history"],
    }
    return {
        "division_id": DIVISION_ID,
        "anchor": {"policy_ref": "paintbot:v12", "policy_version_id": "00000000-0000-0000-0000-000000000012"},
        "note": None,
        "window": {"rounds": 4, "episodes_scanned": 40, "oldest_round_at": "2026-08-20T00:00:00Z"},
        "mode_mix": {"fractions": {"1v1": 1.0}, "source": "history"},
        "modes": {"1v1": mode},
        "league_pooled": {"1v1": mode},
        "table": [
            {
                "elo": 50,
                "per_mode_n_per_arm": {"1v1": 758},
                "blended_n_per_arm": 758,
                "blended_n_range": [600, 1000],
                "one_arm_n": None,
                "anchor": "paintbot:v12",
            }
        ],
    }


def _division(division_id: str, level: int, division_type: str = "competition") -> dict:
    return {
        "id": division_id,
        "name": f"Division {level}",
        "level": level,
        "type": division_type,
        "hidden": False,
        "league": {
            "id": LEAGUE_ID,
            "name": "Paint League",
            "game": {
                "id": "game_00000000-0000-0000-0000-000000000004",
                "name": "Paint Arena",
                "created_at": "2026-08-01T00:00:00Z",
            },
            "created_at": "2026-08-01T00:00:00Z",
        },
        "created_at": "2026-08-01T00:00:00Z",
    }


def test_direct_division_json_sends_requested_parameters(httpserver: HTTPServer) -> None:
    def handler(request: Request) -> Response:
        assert json.loads(request.get_data()) == {
            "policy_ref": "paintbot:v12",
            "elo_grid": [25.0, 50.0],
            "alpha": 0.05,
            "power": 0.8,
        }
        return Response(json.dumps(_report()), content_type="application/json")

    httpserver.expect_request(
        f"/observatory/v2/divisions/{DIVISION_ID}/power-analysis",
        method="POST",
        headers={"Authorization": "Bearer token"},
    ).respond_with_handler(handler)
    result = CliRunner().invoke(
        app,
        [
            "power-analysis",
            DIVISION_ID,
            "--policy",
            "paintbot:v12",
            "--elo",
            "25,50",
            "--server",
            httpserver.url_for(""),
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["table"][0]["blended_n_per_arm"] == 758


def test_league_selects_lowest_level_competition_division(httpserver: HTTPServer) -> None:
    httpserver.expect_request("/observatory/v2/divisions", method="GET").respond_with_json(
        [
            _division(OTHER_DIVISION_ID, 2),
            _division(DIVISION_ID, 1),
            _division("div_00000000-0000-0000-0000-000000000005", 0, "practice"),
        ]
    )
    httpserver.expect_request(
        f"/observatory/v2/divisions/{DIVISION_ID}/power-analysis", method="POST"
    ).respond_with_json(_report())
    result = CliRunner().invoke(app, ["power-analysis", LEAGUE_ID, "--server", httpserver.url_for(""), "--json"])
    assert result.exit_code == 0, result.output


def test_human_output_has_parameters_table_and_flag(httpserver: HTTPServer) -> None:
    httpserver.expect_request(
        f"/observatory/v2/divisions/{DIVISION_ID}/power-analysis", method="POST"
    ).respond_with_json(_report())
    result = CliRunner().invoke(app, ["power-analysis", DIVISION_ID, "--server", httpserver.url_for("")])
    assert result.exit_code == 0, result.output
    assert "Measured parameters" in result.output
    assert "Episodes per arm" in result.output
    assert "low_history:" in result.output


def test_human_output_renders_every_backend_flag(httpserver: HTTPServer) -> None:
    report = _report()
    report["league_pooled"]["ffa4"] = {
        **report["league_pooled"]["1v1"],
        "episodes_used": 0,
        "wins": 0,
        "losses": 0,
        "flags": ["no_usable_history"],
    }
    httpserver.expect_request(
        f"/observatory/v2/divisions/{DIVISION_ID}/power-analysis", method="POST"
    ).respond_with_json(report)
    result = CliRunner().invoke(app, ["power-analysis", DIVISION_ID, "--server", httpserver.url_for("")])
    assert result.exit_code == 0, result.output
    assert "no_usable_history:" in result.output


def test_empty_elo_is_rejected_before_api_call() -> None:
    result = CliRunner().invoke(app, ["power-analysis", DIVISION_ID, "--elo", ",,"])
    assert result.exit_code != 0
    assert "non-empty comma-separated" in result.output
