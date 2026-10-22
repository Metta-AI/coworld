import json

import pytest
from pytest_httpserver import HTTPServer
from typer.testing import CliRunner

from coworld.cli import app


@pytest.mark.parametrize("token", ["user-token", "ply_player-token"])
@pytest.mark.parametrize("json_output", [False, True])
def test_credits_uses_active_identity(
    httpserver: HTTPServer, monkeypatch: pytest.MonkeyPatch, token: str, json_output: bool
) -> None:
    monkeypatch.setattr("softmax_client.credentials.load_current_token", lambda *, server: token)
    payload = {
        "status": {
            "balance_credits": 123.5,
            "max_balance_credits": 200,
            "refill_credits": 10,
            "refill_cadence": "day",
            "next_refill_at": "2026-10-09T07:00:00Z",
            "credits_per_usd": 10,
            "spent_this_period_credits": 76.5,
            "enforced": True,
        },
        "recent_requests": [
            {
                "experience_request_id": "xreq_recent",
                "coworld": "paintarena",
                "episodes": 2,
                "compute_cost_credits": 3.0,
                "last_activity_at": "2026-10-08T00:00:00Z",
            }
        ],
    }
    httpserver.expect_request(
        "/observatory/usage/me/credits", method="GET", headers={"Authorization": f"Bearer {token}"}
    ).respond_with_json(payload)

    args = ["credits", "--server", httpserver.url_for("")]
    if json_output:
        args.append("--json")
    result = CliRunner().invoke(app, args)

    assert result.exit_code == 0, result.output
    if json_output:
        assert json.loads(result.output) == payload
    else:
        assert "XP credits remaining: 123.5 / 200" in result.output
        assert "Refill: 10 every day" in result.output
