import json
from pathlib import Path
from urllib.parse import urlencode

import pytest
from pytest_httpserver import HTTPServer
from typer.testing import CliRunner
from werkzeug.wrappers import Response

from coworld.api_client import EpisodeChangePage
from coworld.cli import app
from coworld.episode_workflows import WatchCheckpoint

BATCH = "xreq_00000000-0000-0000-0000-000000000001"
EPISODE = "ereq_00000000-0000-0000-0000-000000000002"
NOW = "2026-09-24T12:00:00Z"


@pytest.fixture(autouse=True)
def login(monkeypatch):
    monkeypatch.setattr("softmax.auth.load_current_token", lambda **kwargs: "private-api-token")


def test_bulk_jsonl_streams_pages_without_individual_episode_reads(httpserver: HTTPServer):
    for cursor, next_cursor in [(None, "next"), ("next", None)]:
        query = {"ids": [BATCH, BATCH.replace("001", "003")], "view": "results", "limit": "200"}
        if cursor is not None:
            query["cursor"] = cursor
        httpserver.expect_ordered_request(
            "/observatory/v2/episode-requests", query_string=urlencode(query, doseq=True)
        ).respond_with_json(
            {
                "entries": [],
                "unavailable_ids": [],
                "next_cursor": next_cursor,
                "observed_at": NOW,
            }
        )
    result = CliRunner().invoke(
        app,
        [
            "xp-request",
            "episodes",
            BATCH,
            BATCH.replace("001", "003"),
            "--view",
            "results",
            "--jsonl",
            "--server",
            httpserver.url_for(""),
        ],
    )
    assert result.exit_code == 0, result.output
    assert [json.loads(line)["next_cursor"] for line in result.stdout.splitlines()] == ["next", None]
    assert len(httpserver.log) == 2


def test_watch_resumes_after_rate_limit_with_equal_revision_update(httpserver: HTTPServer, tmp_path: Path):
    checkpoint = tmp_path / "watch.json"
    initial = {
        "phase": "snapshot",
        "batches": [{"id": BATCH, "status": "running", "episode_count": 1}],
        "entries": [
            {
                "id": EPISODE,
                "experience_request_id": BATCH,
                "revision": 7,
                "removed": False,
                "episode": {
                    "id": EPISODE,
                    "experience_request_id": BATCH,
                    "created_at": NOW,
                    "status": "running",
                    "error_type": None,
                    "evidence_state": "pending",
                },
            }
        ],
        "next_cursor": "saved",
        "has_more": True,
        "poll_after_seconds": 2,
        "expires_at": NOW,
    }
    httpserver.expect_ordered_request("/observatory/v2/episode-requests/changes").respond_with_json(initial)
    httpserver.expect_ordered_request("/observatory/v2/episode-requests/changes").respond_with_json(
        {},
        status=429,
        headers={"Retry-After": "60", "X-RateLimit-Outcome": "rejected"},
    )
    args = [
        "xp-request",
        "watch",
        BATCH,
        "--checkpoint",
        str(checkpoint),
        "--timeout",
        "1",
        "--jsonl",
        "--server",
        httpserver.url_for(""),
    ]
    first = CliRunner().invoke(app, args)
    assert first.exit_code == 3, first.output
    saved = WatchCheckpoint.model_validate_json(checkpoint.read_text())
    assert saved.cursor == "saved"
    EpisodeChangePage.model_validate_json(first.stdout.splitlines()[0])
    initial["phase"] = "changes"
    initial["has_more"] = False
    initial["next_cursor"] = "finished"
    initial["batches"][0]["status"] = "completed"
    initial["entries"][0]["episode"]["status"] = "completed"
    httpserver.expect_ordered_request(
        "/observatory/v2/episode-requests/changes",
        query_string={"ids": BATCH, "view": "progress", "limit": "200", "cursor": "saved"},
    ).respond_with_json(initial)
    resumed = CliRunner().invoke(app, args)
    assert resumed.exit_code == 0, resumed.output
    assert WatchCheckpoint.model_validate_json(checkpoint.read_text()).cursor == "finished"
    assert "private-api-token" not in checkpoint.read_text()


def test_download_refreshes_expired_url_and_verifies_local_resume(httpserver: HTTPServer, tmp_path: Path):
    body = b"episode evidence"
    entry = {
        "episode_request_id": EPISODE,
        "category": "results",
        "position": None,
        "artifact_id": "job:results:None",
        "version": "v1",
        "filename": "results.json",
        "state": "ready",
        "media_type": "application/json",
        "size": len(body),
        "etag": '"stable"',
        "url": httpserver.url_for("/expired?signature=secret"),
    }
    httpserver.expect_ordered_request("/observatory/v2/episode-requests/download-manifest").respond_with_json(
        {
            "entries": [entry],
            "unavailable_ids": [],
            "next_cursor": None,
        }
    )
    httpserver.expect_ordered_request("/expired", query_string="signature=secret").respond_with_data(
        "expired", status=403
    )
    entry = {**entry, "url": httpserver.url_for("/file?signature=secret")}
    httpserver.expect_request("/observatory/v2/episode-requests/download-manifest").respond_with_json(
        {
            "entries": [entry],
            "unavailable_ids": [],
            "next_cursor": None,
        }
    )
    downloads = []

    def storage(request):
        assert "Authorization" not in request.headers
        assert request.headers["If-Match"] == '"stable"'
        downloads.append(request.path)
        return Response(body, headers={"ETag": '"stable"'})

    httpserver.expect_request("/file", query_string="signature=secret").respond_with_handler(storage)
    args = [
        "xp-request",
        "download",
        BATCH,
        "--include",
        "results",
        "--directory",
        str(tmp_path),
        "--server",
        httpserver.url_for(""),
    ]
    first = CliRunner().invoke(app, args)
    assert first.exit_code == 0, first.output
    manifest = tmp_path / "manifest.jsonl"
    result = json.loads(manifest.read_text().splitlines()[-1])
    target = tmp_path / result["path"]
    assert target.read_bytes() == body
    assert "signature" not in manifest.read_text()
    assert "private-api-token" not in manifest.read_text()
    assert CliRunner().invoke(app, args).exit_code == 0
    assert len(downloads) == 1
    target.write_bytes(b"corrupt evidence")
    assert CliRunner().invoke(app, args).exit_code == 0
    assert target.read_bytes() == body
    assert len(downloads) == 2


def test_download_pending_files_return_partial_exit(httpserver: HTTPServer, tmp_path: Path):
    httpserver.expect_request("/observatory/v2/episode-requests/download-manifest").respond_with_json(
        {
            "entries": [
                {
                    "episode_request_id": EPISODE,
                    "category": "results",
                    "position": None,
                    "artifact_id": "job:results",
                    "version": None,
                    "filename": "results.json",
                    "state": "pending",
                    "media_type": "application/json",
                }
            ],
            "unavailable_ids": [],
            "next_cursor": None,
        }
    )
    result = CliRunner().invoke(
        app,
        [
            "xp-request",
            "download",
            BATCH,
            "--include",
            "results",
            "-d",
            str(tmp_path),
            "--server",
            httpserver.url_for(""),
        ],
    )
    assert result.exit_code == 2, result.output
    assert json.loads((tmp_path / "manifest.jsonl").read_text())["state"] == "pending"
