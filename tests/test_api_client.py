"""Unit tests for ``CoworldApiClient._request`` body-handling contract.

The original bug (#15212) was an unhandled ``pydantic.ValidationError`` when
``coworld results <empty_division>`` returned a JSON ``null`` leaderboard body
into a strict ``list[LeaderboardEntryPublic]`` response type. The fix widens
``get_division_leaderboard``'s response type to ``list[...] | None`` and
coalesces to ``[]`` at the call site.

These tests pin ``_request``'s strict validation contract so future schema
changes can't silently start coercing edge responses (null/empty) without
showing up in CI.
"""

from collections.abc import Iterator
from typing import Any

import pytest
from pydantic import ValidationError
from pytest_httpserver import HTTPServer

from coworld.api_client import CoworldApiClient, LeaderboardEntryPublic
from coworld.upload import CoworldUploadClient


@pytest.fixture
def client(httpserver: HTTPServer) -> Iterator[CoworldApiClient]:
    with CoworldApiClient(server_url=httpserver.url_for(""), token="token") as c:
        yield c


@pytest.mark.parametrize(
    "body, response_type, expected",
    [
        # Original bug: null body validated against a strict `list[Model]` must
        # raise. `coworld results <empty_division>` crashed on this exact path
        # pre-#15212; pinning it forces any future "helpful" coercion in
        # `_request` to be a deliberate, reviewed change.
        pytest.param(
            None,
            list[LeaderboardEntryPublic],
            "raises",
            id="null_body_strict_list_raises",
        ),
        # Documented fix path: optional list lets `_request` return None
        # unchanged so call sites can coalesce to [] (or branch on missing).
        pytest.param(
            None,
            list[LeaderboardEntryPublic] | None,
            None,
            id="null_body_optional_list_returns_none",
        ),
        # JSON `[]` for a strict list type round-trips with no coercion.
        pytest.param(
            [],
            list[LeaderboardEntryPublic],
            [],
            id="empty_list_returns_empty_list",
        ),
        # JSON `{}` against a model with required fields must raise; never
        # silently produce a half-built model.
        pytest.param(
            {},
            LeaderboardEntryPublic,
            "raises",
            id="empty_object_for_required_model_raises",
        ),
        # JSON `{}` against `dict[str, Any]` round-trips.
        pytest.param(
            {},
            dict[str, Any],
            {},
            id="empty_object_for_dict_type_returns_empty_dict",
        ),
        # Object missing required Pydantic fields must raise.
        pytest.param(
            {"player_id": "p1"},
            LeaderboardEntryPublic,
            "raises",
            id="missing_required_field_raises",
        ),
    ],
)
def test_request_pins_null_and_empty_body_behavior(
    httpserver: HTTPServer,
    client: CoworldApiClient,
    body: Any,
    response_type: Any,
    expected: Any,
) -> None:
    httpserver.expect_request("/observatory/edge", method="GET").respond_with_json(body)

    if expected == "raises":
        with pytest.raises(ValidationError):
            client._request("GET", "/edge", response_type)
    else:
        assert client._request("GET", "/edge", response_type) == expected


def test_elevated_flag_defaults_off(httpserver: HTTPServer) -> None:
    # A fresh client MUST NOT send X-Use-Elevated-Privileges — the header is opt-in per
    # invocation via the top-level `coworld --elevated` flag. Any regression here would
    # silently re-grant Softmax team access to every CLI call.
    CoworldApiClient.set_elevated(False)  # reset in case of test-ordering carryover
    with CoworldApiClient(server_url=httpserver.url_for(""), token="usr_test") as client:
        headers = client._headers()
    assert headers == {"Authorization": "Bearer usr_test"}


def test_elevated_flag_adds_header_on_user_token(httpserver: HTTPServer) -> None:
    CoworldApiClient.set_elevated(True)
    try:
        with CoworldApiClient(server_url=httpserver.url_for(""), token="usr_test") as client:
            headers = client._headers()
        assert headers == {
            "Authorization": "Bearer usr_test",
            "X-Use-Elevated-Privileges": "true",
        }
    finally:
        CoworldApiClient.set_elevated(False)


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


# CoworldUploadClient shares the elevation contract with CoworldApiClient (both are
# used side by side by coworld CLI commands and must not diverge). These tests mirror
# the ones above so regressions on one client don't sneak past the other.


def test_upload_client_elevated_defaults_off(httpserver: HTTPServer) -> None:
    CoworldUploadClient.set_elevated(False)
    with CoworldUploadClient(server_url=httpserver.url_for(""), token="usr_test") as client:
        headers = client._headers()
    assert headers == {"Authorization": "Bearer usr_test"}


def test_upload_client_elevated_adds_header_on_user_token(httpserver: HTTPServer) -> None:
    CoworldUploadClient.set_elevated(True)
    try:
        with CoworldUploadClient(server_url=httpserver.url_for(""), token="usr_test") as client:
            headers = client._headers()
        assert headers == {
            "Authorization": "Bearer usr_test",
            "X-Use-Elevated-Privileges": "true",
        }
    finally:
        CoworldUploadClient.set_elevated(False)


def test_upload_client_elevated_refuses_player_token(httpserver: HTTPServer) -> None:
    CoworldUploadClient.set_elevated(True)
    try:
        with CoworldUploadClient(server_url=httpserver.url_for(""), token="ply_test") as client:
            with pytest.raises(RuntimeError, match="player-subject token"):
                client._headers()
    finally:
        CoworldUploadClient.set_elevated(False)
