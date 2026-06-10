"""`coworld player` mounts softmax-cli's player app; the full command suite is
tested in packages/softmax-cli/tests/test_player_cli.py. This covers the mount
and the end-to-end inheritance coworld relies on."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pytest_httpserver import HTTPServer
from typer.testing import CliRunner

from coworld.cli import app
from softmax.auth import load_current_token

PLAYER_ALPHA = {
    "id": "ply_00000000-0000-0000-0000-0000000000a1",
    "name": "Alpha",
    "is_default": True,
    "avatar_url": None,
    "created_at": "2026-06-05T12:00:00Z",
    "disabled_at": None,
    "user_id": "usr_owner",
}


@pytest.fixture(autouse=True)
def _sandbox_credentials(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    # Isolate ~/.softmax/credentials.yaml under tmp.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("softmax.auth.load_user_token", lambda *, server: "user-token")


def test_player_commands_are_mounted() -> None:
    result = CliRunner().invoke(app, ["player", "--help"])

    assert result.exit_code == 0, result.output
    for command in ("list", "use", "unset"):
        assert command in result.output


def test_use_via_coworld_sets_token_for_coworld_commands(httpserver: HTTPServer) -> None:
    server = httpserver.url_for("")
    expires_at = (datetime.now(UTC) + timedelta(hours=24)).isoformat()
    httpserver.expect_request(
        "/observatory/players",
        method="GET",
        headers={"Authorization": "Bearer user-token"},
    ).respond_with_json([PLAYER_ALPHA])
    httpserver.expect_request(f"/observatory/players/{PLAYER_ALPHA['id']}/login", method="POST").respond_with_json(
        {"player_id": PLAYER_ALPHA["id"], "token": "ply_minted", "expires_at": expires_at}
    )

    result = CliRunner().invoke(app, ["player", "use", PLAYER_ALPHA["id"], "--server", server])

    assert result.exit_code == 0, result.output
    # Every coworld command resolves its token via load_current_token, so it
    # now acts as the player.
    assert load_current_token(server=server) == "ply_minted"
