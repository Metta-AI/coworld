"""Cursor pagination for the bare-list catalog endpoints.

The server emits the ``X-Next-Cursor`` continuation header while
``/v2/coworlds``, ``/v2/container_images``, and ``/v2/reporters`` still return
bare-list bodies. The client walks pages by echoing the opaque token back as
the ``cursor`` query param and stops when the header is absent — it never
constructs tokens itself, so the server owns the ordering.
"""

from __future__ import annotations

from typing import Any

from pytest_httpserver import HTTPServer

from coworld.api_client import CoworldApiClient
from coworld.config import NEXT_CURSOR_HEADER
from coworld.upload import CoworldUploadClient


def _coworld_entry(index: int, *, name: str | None = None) -> dict[str, Any]:
    return {
        "id": f"cow_{index}",
        "name": name or f"coworld-{index}",
        "version": "1.0.0",
        "manifest_summary": {
            "description": "A compact summary",
            "owner": "coworld@example.com",
            "variants": [{"id": "default", "name": "Default"}],
            "role_counts": {
                "player": 1,
                "commissioner": 0,
                "grader": 0,
                "diagnoser": 0,
                "optimizer": 0,
            },
        },
        "manifest_hash": f"hash-{index}",
        "size_bytes": 1,
        "created_at": "2026-08-20T12:00:00Z",
        "canonical": False,
    }


def _image_entry(index: int) -> dict[str, Any]:
    return {
        "id": f"img_{index}",
        "name": f"image-{index}",
        "version": index,
        "client_hash": None,
        "status": "ready",
    }


def _reporter_entry(index: int) -> dict[str, Any]:
    return {
        "id": f"rptr_{index}",
        "name": f"reporter-{index}",
        "display_name": f"Reporter {index}",
        "description": "d",
        "user_id": "owner@example.com",
        "created_at": "2026-08-20T12:00:00Z",
    }


def _league() -> dict[str, Any]:
    return {
        "id": "league_1",
        "name": "Paint League",
        "game": {"id": "game_1", "name": "Paint Arena", "created_at": "2026-08-20T12:00:00Z"},
        "created_at": "2026-08-20T12:00:00Z",
    }


def _policy_version() -> dict[str, Any]:
    return {
        "id": "00000000-0000-0000-0000-000000000031",
        "policy": {"id": "00000000-0000-0000-0000-000000000032", "name": "paintbot"},
        "version": 3,
    }


def _membership() -> dict[str, Any]:
    return {
        "id": "lpm_1",
        "status": "competing",
        "league": _league(),
        "division": {
            "id": "division_1",
            "name": "Bronze",
            "level": 1,
            "type": "competition",
            "hidden": False,
            "league": _league(),
            "created_at": "2026-08-20T12:00:00Z",
        },
        "policy_version": _policy_version(),
        "created_at": "2026-08-20T12:00:00Z",
    }


def _submission() -> dict[str, Any]:
    return {
        "id": "submission_1",
        "status": "accepted",
        "league": _league(),
        "policy_version": _policy_version(),
        "created_at": "2026-08-20T12:00:00Z",
    }


def test_list_coworlds_page_carries_next_cursor(httpserver: HTTPServer) -> None:
    httpserver.expect_request("/observatory/v2/coworlds/summaries", query_string={"limit": "5"}).respond_with_json(
        [_coworld_entry(0)], headers={NEXT_CURSOR_HEADER: "tok-1"}
    )
    with CoworldUploadClient(server_url=httpserver.url_for(""), token="usr_test") as client:
        page = client.list_coworlds(limit=5)
    assert [c.name for c in page.entries] == ["coworld-0"]
    assert page.next_cursor == "tok-1"


def test_find_coworld_walks_pages_by_cursor(httpserver: HTTPServer) -> None:
    httpserver.expect_request("/observatory/v2/coworlds/summaries", query_string={"limit": "200"}).respond_with_json(
        [_coworld_entry(0)], headers={NEXT_CURSOR_HEADER: "page-2"}
    )
    httpserver.expect_request(
        "/observatory/v2/coworlds/summaries", query_string={"limit": "200", "cursor": "page-2"}
    ).respond_with_json([_coworld_entry(1)])
    with CoworldUploadClient(server_url=httpserver.url_for(""), token="usr_test") as client:
        found = client.find_coworld("cow_1")
    assert found is not None
    assert found.name == "coworld-1"


def test_find_coworld_stops_when_header_absent(httpserver: HTTPServer) -> None:
    # A missing continuation header is the end of the listing, even when the
    # page came back full.
    httpserver.expect_request("/observatory/v2/coworlds/summaries", query_string={"limit": "200"}).respond_with_json(
        [_coworld_entry(0)]
    )
    with CoworldUploadClient(server_url=httpserver.url_for(""), token="usr_test") as client:
        assert client.find_coworld("cow_missing") is None


def test_iter_coworlds_by_name_collects_matches_across_pages(httpserver: HTTPServer) -> None:
    httpserver.expect_request("/observatory/v2/coworlds/summaries", query_string={"limit": "200"}).respond_with_json(
        [_coworld_entry(0, name="paint-arena"), _coworld_entry(1)],
        headers={NEXT_CURSOR_HEADER: "page-2"},
    )
    httpserver.expect_request(
        "/observatory/v2/coworlds/summaries", query_string={"limit": "200", "cursor": "page-2"}
    ).respond_with_json([_coworld_entry(2, name="paint_arena")])
    with CoworldUploadClient(server_url=httpserver.url_for(""), token="usr_test") as client:
        matches = list(client.iter_coworlds_by_name("paint-arena"))
    assert [c.id for c in matches] == ["cow_0", "cow_2"]


def test_list_images_page_carries_next_cursor(httpserver: HTTPServer) -> None:
    httpserver.expect_request("/observatory/v2/container_images", query_string={"limit": "2"}).respond_with_json(
        [_image_entry(0), _image_entry(1)], headers={NEXT_CURSOR_HEADER: "tok-2"}
    )
    httpserver.expect_request(
        "/observatory/v2/container_images", query_string={"limit": "2", "cursor": "tok-2"}
    ).respond_with_json([_image_entry(2)])
    with CoworldUploadClient(server_url=httpserver.url_for(""), token="usr_test") as client:
        first = client.list_images(limit=2)
        second = client.list_images(limit=2, cursor=first.next_cursor)
    assert first.next_cursor == "tok-2"
    assert [image.name for image in second.entries] == ["image-2"]
    assert second.next_cursor is None


def test_list_reporters_page_carries_next_cursor(httpserver: HTTPServer) -> None:
    httpserver.expect_request(
        "/observatory/v2/reporters", query_string={"mode": "all", "limit": "200"}
    ).respond_with_json([_reporter_entry(0)], headers={NEXT_CURSOR_HEADER: "tok-3"})
    with CoworldApiClient(server_url=httpserver.url_for(""), token="usr_test") as client:
        page = client.list_reporters()
    assert [r.name for r in page.entries] == ["reporter-0"]
    assert page.next_cursor == "tok-3"


def test_list_reporters_resumes_from_cursor(httpserver: HTTPServer) -> None:
    httpserver.expect_request(
        "/observatory/v2/reporters", query_string={"mode": "all", "limit": "200", "cursor": "tok-3"}
    ).respond_with_json([])
    with CoworldApiClient(server_url=httpserver.url_for(""), token="usr_test") as client:
        page = client.list_reporters(cursor="tok-3")
    assert page.entries == []
    assert page.next_cursor is None


def test_list_memberships_carries_and_resumes_from_cursor(httpserver: HTTPServer) -> None:
    httpserver.expect_request(
        "/observatory/v2/league-policy-memberships",
        query_string={
            "active_only": "false",
            "champions_only": "false",
            "mine": "true",
            "limit": "25",
            "cursor": "membership-page-2",
        },
    ).respond_with_json([_membership()], headers={NEXT_CURSOR_HEADER: "membership-page-3"})
    with CoworldApiClient(server_url=httpserver.url_for(""), token="usr_test") as client:
        page = client.list_memberships(mine=True, limit=25, cursor="membership-page-2")
    assert [membership.id for membership in page.entries] == ["lpm_1"]
    assert page.next_cursor == "membership-page-3"


def test_list_memberships_omits_limit_before_server_cutover(httpserver: HTTPServer) -> None:
    httpserver.expect_request(
        "/observatory/v2/league-policy-memberships",
        query_string={"active_only": "false", "champions_only": "false", "mine": "false"},
    ).respond_with_json([_membership()])
    with CoworldApiClient(server_url=httpserver.url_for(""), token="usr_test") as client:
        page = client.list_memberships()
    assert [membership.id for membership in page.entries] == ["lpm_1"]
    assert page.next_cursor is None


def test_list_submissions_carries_and_resumes_from_cursor(httpserver: HTTPServer) -> None:
    httpserver.expect_request(
        "/observatory/v2/league-submissions",
        query_string={"mine": "true", "limit": "25", "cursor": "submission-page-2"},
    ).respond_with_json([_submission()], headers={NEXT_CURSOR_HEADER: "submission-page-3"})
    with CoworldApiClient(server_url=httpserver.url_for(""), token="usr_test") as client:
        page = client.list_submissions(mine=True, limit=25, cursor="submission-page-2")
    assert [submission.id for submission in page.entries] == ["submission_1"]
    assert page.next_cursor == "submission-page-3"


def test_list_submissions_omits_limit_before_server_cutover(httpserver: HTTPServer) -> None:
    httpserver.expect_request(
        "/observatory/v2/league-submissions",
        query_string={"mine": "false"},
    ).respond_with_json([_submission()])
    with CoworldApiClient(server_url=httpserver.url_for(""), token="usr_test") as client:
        page = client.list_submissions()
    assert [submission.id for submission in page.entries] == ["submission_1"]
    assert page.next_cursor is None


def test_list_rounds_resumes_from_cursor(httpserver: HTTPServer) -> None:
    httpserver.expect_request(
        "/observatory/v2/rounds",
        query_string={"limit": "25", "cursor": "round-page-2"},
    ).respond_with_json({"entries": [], "next_cursor": None})
    with CoworldApiClient(server_url=httpserver.url_for(""), token="usr_test") as client:
        page = client.list_rounds(cursor="round-page-2")
    assert page.entries == []
    assert page.next_cursor is None


def test_list_experience_requests_resumes_from_cursor(httpserver: HTTPServer) -> None:
    httpserver.expect_request(
        "/observatory/v2/experience-requests",
        query_string={"mine": "false", "limit": "50", "cursor": "xp-page-2"},
    ).respond_with_json({"entries": [], "next_cursor": None})
    with CoworldApiClient(server_url=httpserver.url_for(""), token="usr_test") as client:
        page = client.list_experience_requests(cursor="xp-page-2")
    assert page.entries == []
    assert page.next_cursor is None
