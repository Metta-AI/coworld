import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from pytest_httpserver import HTTPServer
from typer.testing import CliRunner
from werkzeug import Request, Response

from coworld.cli import app
from coworld.feed_cli import parse_feed_post, print_feed_reminder

NOW = "2026-10-07T12:00:00Z"
POST_ID = "00000000-0000-0000-0000-000000000099"
TEXT = "Climbed from 14th to 9th after the new opener. Nothing needs you."
LINK = "https://softmax.com/observatory/replays/ep_1"
REPORT_URL = "https://softmax.com/r/abc123"
POSTS_PATH = "/observatory/v2/coworlds/paintarena/feed-posts"
CHECK_PATH = "/observatory/v2/coworlds/paintarena/feed-posts/check"


@pytest.fixture(autouse=True)
def _fake_softmax_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("softmax.auth.load_current_token", lambda *, server: "token")


def _post(link_url: str | None = None, link_kind: str | None = None) -> dict[str, object]:
    return {
        "id": POST_ID,
        "coworld_name": "paintarena",
        "who": "roger",
        "author_name": "Me",
        "author_avatar_url": None,
        "text": TEXT,
        "link_url": link_url,
        "link_kind": link_kind,
        "link_title": None,
        "link_subtitle": None,
        "link_image_url": None,
        "report_code": None,
        "owner_user_id": "user_00000000-0000-0000-0000-000000000071",
        "player_id": None,
        "created_at": NOW,
    }


def _round(round_id: str, number: int) -> dict[str, object]:
    return {
        "league_id": "league_1",
        "league_name": "Paint Arena League",
        "round_id": round_id,
        "round_number": number,
        "closed_at": f"2026-10-{number:02d}T12:00:00Z",
    }


def _post_args(path: Path, httpserver: HTTPServer) -> list[str]:
    return ["feed", "post", str(path), "--coworld", "paintarena", "--hat", "roger", "--server", httpserver.url_for("/")]


def test_parse_without_front_matter_is_all_text() -> None:
    front_matter, text = parse_feed_post(f"\n{TEXT}\n")

    assert front_matter.link is None
    assert front_matter.report is None
    assert text == TEXT


def test_parse_link_keeps_colons_and_strips_matching_quotes() -> None:
    plain, plain_text = parse_feed_post(f"---\nlink: {LINK}\n---\n{TEXT}\n")
    quoted, _ = parse_feed_post(f'---\nlink: "{LINK}"\n---\n{TEXT}\n')

    assert plain.link == LINK
    assert plain_text == TEXT
    assert quoted.link == LINK


def test_parse_line_without_colon_raises() -> None:
    with pytest.raises(ValueError, match="key: value"):
        parse_feed_post("---\nlink\n---\ntext\n")


@pytest.mark.parametrize(
    ("meta", "match"),
    [
        ("summary: old card field", "summary"),
        ("report: report.md", "report"),
        ("link: report.pdf", r"\.md or \.html"),
    ],
)
def test_parse_rejects_bad_front_matter(meta: str, match: str) -> None:
    with pytest.raises(ValidationError, match=match):
        parse_feed_post(f"---\n{meta}\n---\ntext\n")


def test_feed_post_sends_text_and_link(httpserver: HTTPServer, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def handler(request: Request) -> Response:
        captured["body"] = json.loads(request.get_data())
        captured["auth"] = request.headers.get("Authorization")
        return Response(json.dumps(_post(LINK, "link")), status=201, content_type="application/json")

    httpserver.expect_request(POSTS_PATH, method="POST").respond_with_handler(handler)
    message = tmp_path / "message.md"
    message.write_text(f"---\nlink: {LINK}\n---\n{TEXT}\n", encoding="utf-8")

    result = CliRunner().invoke(app, _post_args(message, httpserver))

    assert result.exit_code == 0, result.output
    body = captured["body"]
    assert isinstance(body, dict)
    assert body.pop("idempotency_key")
    assert body == {"text": TEXT, "link_url": LINK, "report": None, "who": "roger"}
    assert captured["auth"] == "Bearer token"
    assert result.output.strip() == f"Posted {POST_ID}"


def test_feed_post_attaches_report_relative_to_message(httpserver: HTTPServer, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def handler(request: Request) -> Response:
        captured["body"] = json.loads(request.get_data())
        return Response(json.dumps(_post(REPORT_URL, "report")), status=201, content_type="application/json")

    httpserver.expect_request(POSTS_PATH, method="POST").respond_with_handler(handler)
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "week.html").write_text("<h1>Week</h1>", encoding="utf-8")
    message = tmp_path / "message.md"
    message.write_text(f"---\nlink: reports/week.html\n---\n{TEXT}\n", encoding="utf-8")

    result = CliRunner().invoke(app, _post_args(message, httpserver))

    assert result.exit_code == 0, result.output
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["link_url"] is None
    assert body["report"] == {"format": "html", "content": "<h1>Week</h1>"}
    assert f"Posted {POST_ID}" in result.output
    assert f"Report: {REPORT_URL}" in result.output


def test_feed_post_rejects_empty_text(tmp_path: Path) -> None:
    message = tmp_path / "message.md"
    message.write_text(f"---\nlink: {LINK}\n---\n\n", encoding="utf-8")

    result = CliRunner().invoke(app, ["feed", "post", str(message), "--coworld", "paintarena", "--hat", "roger"])

    assert result.exit_code != 0
    assert isinstance(result.exception, ValueError)
    assert "no message text" in str(result.exception)


def test_feed_post_warns_past_visible_words(httpserver: HTTPServer, tmp_path: Path) -> None:
    httpserver.expect_request(POSTS_PATH, method="POST").respond_with_json(_post(), status=201)
    message = tmp_path / "message.md"
    message.write_text("word " * 351, encoding="utf-8")

    result = CliRunner(mix_stderr=False).invoke(app, _post_args(message, httpserver))

    assert result.exit_code == 0, result.output
    assert "Only the first 350 words show; the rest is behind 'see more'." in result.stderr
    assert f"Posted {POST_ID}" in result.stdout


@pytest.mark.parametrize("explicit_key", [None, "daily-update-2026-10-08"])
def test_feed_post_reuses_key_after_failed_response(
    httpserver: HTTPServer, tmp_path: Path, explicit_key: str | None
) -> None:
    captured: list[dict[str, object]] = []
    fail_response = True

    def handler(request: Request) -> Response:
        captured.append(json.loads(request.get_data()))
        if fail_response:
            return Response("response lost after commit", status=500)
        return Response(json.dumps(_post(REPORT_URL, "report")), status=201, content_type="application/json")

    httpserver.expect_request(POSTS_PATH, method="POST").respond_with_handler(handler)
    report = tmp_path / "report.md"
    report.write_text("# Week\n", encoding="utf-8")
    message = tmp_path / "message.md"
    message.write_text(f"---\nlink: report.md\n---\n{TEXT}\n", encoding="utf-8")
    args = _post_args(message, httpserver)
    if explicit_key is not None:
        args.extend(["--idempotency-key", explicit_key])

    failed = CliRunner().invoke(app, args)
    assert failed.exit_code != 0

    fail_response = False
    retried = CliRunner().invoke(app, args)
    assert retried.exit_code == 0, retried.output
    keys = {body["idempotency_key"] for body in captured}
    assert len(keys) == 1
    if explicit_key is not None:
        assert keys == {explicit_key}

    report.write_text("# Week\nNew result.\n", encoding="utf-8")
    changed = CliRunner().invoke(app, args)
    assert changed.exit_code == 0, changed.output
    assert (captured[-1]["idempotency_key"] in keys) == (explicit_key is not None)


def test_reminder_prints_hello_until_posted_then_lessons_and_closed_rounds(
    httpserver: HTTPServer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    hello = {"kind": "hello", "lesson_angle": None, "customize_reminder": False}
    lesson = {"kind": "lesson", "lesson_angle": "One thing that worked.", "customize_reminder": False}
    checks = [
        {"human_name": "Pawel", "rounds": [_round("round_1", 1)], "sensei_due": hello},
        {"human_name": "Pawel", "rounds": [_round("round_1", 1)], "sensei_due": None},
        {"human_name": None, "rounds": [_round("round_2", 2)], "sensei_due": None},
        {"human_name": "Pawel", "rounds": [_round("round_1", 1)], "sensei_due": None},
        {"human_name": "Pawel", "rounds": [_round("round_2", 2)], "sensei_due": None},
        {"human_name": "Pawel", "rounds": [_round("round_2", 2)], "sensei_due": lesson},
    ]
    httpserver.expect_request(CHECK_PATH, method="GET").respond_with_handler(
        lambda request: Response(json.dumps(checks.pop(0)), content_type="application/json")
    )
    server = httpserver.url_for("/")
    sensei = "uv run coworld feed hat sensei --coworld 'paintarena'"

    # A hello prints on every call while due; the first-seen league is only recorded.
    print_feed_reminder(server=server, coworld_name="paintarena")
    assert capsys.readouterr().out == f"Feed for Pawel: no hello yet, post one now: {sensei}\n"
    print_feed_reminder(server=server, coworld_name="paintarena")
    assert capsys.readouterr().out == ""

    print_feed_reminder(server=server, coworld_name="paintarena")
    assert capsys.readouterr().out == (
        f"Feed for your human: lesson due? {sensei} · urgent? uv run coworld feed hat roger\n"
    )

    # An older round (newest one deleted, or another token's division) stays silent and keeps
    # the newest close time, so the newest round coming back is not news either.
    print_feed_reminder(server=server, coworld_name="paintarena")
    print_feed_reminder(server=server, coworld_name="paintarena")
    assert capsys.readouterr().out == ""

    print_feed_reminder(server=server, coworld_name="paintarena")
    assert capsys.readouterr().out == f"Feed for Pawel: lesson due? {sensei} · urgent? uv run coworld feed hat roger\n"
