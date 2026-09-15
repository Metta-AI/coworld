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
from uuid import UUID

import httpx
import pytest
from pydantic import ValidationError
from pytest_httpserver import HTTPServer

from coworld.api_client import CoworldApiClient, LeaderboardEntryPublic, PolicySelectionAccess, _raise_for_status
from coworld.upload import CoworldUploadClient
from coworld.upload import _raise_for_status as _raise_for_upload_status


@pytest.fixture
def client(httpserver: HTTPServer) -> Iterator[CoworldApiClient]:
    with CoworldApiClient(server_url=httpserver.url_for(""), token="token") as c:
        yield c


@pytest.mark.parametrize("upload", [False, True])
def test_shared_budget_rejection_preserves_retry_guidance(client, httpserver, upload):
    detail = {
        "type": "api_rate_limit_exceeded",
        "retry_after_seconds": 60,
        "documentation_url": "https://docs.softmax.com/guides/rate-limits",
    }
    httpserver.expect_request("/observatory/whoami").respond_with_json(
        {"detail": detail}, status=429, headers={"X-RateLimit-Outcome": "rejected", "Retry-After": "60"}
    )
    with pytest.raises(httpx.HTTPStatusError) as error:
        if upload:
            with CoworldUploadClient(server_url=httpserver.url_for(""), token="token") as upload_client:
                upload_client.whoami()
        else:
            client._get("/whoami", dict)
    assert detail["documentation_url"] in str(error.value)
    assert error.value.response.json()["detail"] == detail
    assert error.value.response.headers["Retry-After"] == "60"


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


def test_get_policy_selection_access(httpserver: HTTPServer, client: CoworldApiClient) -> None:
    policy_id = "10000000-0000-0000-0000-000000000001"
    httpserver.expect_request(
        f"/observatory/v2/policies/{policy_id}/selection-access",
        method="GET",
    ).respond_with_json({"selection_scope": "owner_visible"})

    response = client.get_policy_selection_access(UUID(policy_id))

    assert response == PolicySelectionAccess(selection_scope="owner_visible")


def test_set_policy_selection_access(httpserver: HTTPServer, client: CoworldApiClient) -> None:
    policy_id = "10000000-0000-0000-0000-000000000001"
    httpserver.expect_oneshot_request(
        f"/observatory/v2/policies/{policy_id}/selection-access",
        method="PUT",
        json={"selection_scope": "owner_visible"},
    ).respond_with_json({"selection_scope": "owner_visible"})

    response = client.set_policy_selection_access(UUID(policy_id), selection_scope="owner_visible")

    assert response.selection_scope == "owner_visible"


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


@pytest.mark.parametrize(
    "raise_for_status, response_body",
    [
        pytest.param(_raise_for_status, None, id="api-client-without-detail"),
        pytest.param(_raise_for_status, {"detail": "You do not own this resource"}, id="api-client-with-detail"),
        pytest.param(_raise_for_upload_status, None, id="upload-client-without-detail"),
        pytest.param(
            _raise_for_upload_status, {"detail": "You do not own this resource"}, id="upload-client-with-detail"
        ),
    ],
)
def test_403_errors_suggest_elevated_team_access(raise_for_status: Any, response_body: Any) -> None:
    kwargs = {"json": response_body} if response_body is not None else {}
    response = httpx.Response(
        403,
        request=httpx.Request("GET", "https://softmax.com/observatory/v2/team-resource"),
        **kwargs,
    )

    with pytest.raises(httpx.HTTPStatusError) as error:
        raise_for_status(response)

    assert "coworld --elevated <command>" in str(error.value)
    assert "softmax login" not in str(error.value)
    assert "expired" not in str(error.value)
    if response_body is not None:
        assert response_body["detail"] in str(error.value)


@pytest.mark.parametrize("raise_for_status", [_raise_for_status, _raise_for_upload_status])
def test_403_errors_preserve_non_json_reason(raise_for_status: Any) -> None:
    response = httpx.Response(
        403,
        text="This credential cannot read the catalog",
        request=httpx.Request("GET", "https://softmax.com/api/observatory/v2/coworlds"),
    )
    with pytest.raises(httpx.HTTPStatusError, match="This credential cannot read the catalog"):
        raise_for_status(response)
