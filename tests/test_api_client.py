import pytest
from pytest_httpserver import HTTPServer

from coworld.api_client import CoworldApiClient
from coworld.upload import CoworldUploadClient


def test_elevated_flag_refuses_player_token(httpserver: HTTPServer) -> None:
    # Player-subject credentials (24h tokens minted for tournament/CI runners) are
    # structurally denied team access on the backend, so surfacing --elevated on them
    # would only produce confusing 200-with-no-effect responses. Client-side hard-error.
    CoworldApiClient.set_elevated(True)
    try:
        with CoworldApiClient(server_url=httpserver.url_for(""), token="ply_test") as client:
            with pytest.raises(RuntimeError, match="player-subject token"):
                client._headers()
    finally:
        CoworldApiClient.set_elevated(False)


def test_upload_client_elevated_refuses_player_token(httpserver: HTTPServer) -> None:
    CoworldUploadClient.set_elevated(True)
    try:
        with CoworldUploadClient(server_url=httpserver.url_for(""), token="ply_test") as client:
            with pytest.raises(RuntimeError, match="player-subject token"):
                client._headers()
    finally:
        CoworldUploadClient.set_elevated(False)
