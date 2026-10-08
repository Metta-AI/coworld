import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from pytest_httpserver import HTTPServer
from typer.testing import CliRunner
from werkzeug import Request, Response

from coworld.cli import app
from coworld.feed_cli import parse_feed_card

NOW = "2026-10-07T12:00:00Z"
CARD_ID = "00000000-0000-0000-0000-000000000099"
SUMMARY = "What happened in the last 24h? Climbed from 14th to 9th; two practice runs; one upload."
BODY = "#### Standing\nMoved up 5 places.\n\n| run | status |\n| --- | --- |\n| xp-42 | finished |\n"
CARD_MD = f"---\ntype: update\nsummary: {SUMMARY}\n---\n{BODY}"


@pytest.fixture(autouse=True)
def _fake_softmax_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("softmax.auth.load_current_token", lambda *, server: "token")


def _card(kind: str = "update", summary: str = SUMMARY, body: str = BODY) -> dict[str, object]:
    return {
        "id": CARD_ID,
        "coworld_name": "paintarena",
        "kind": kind,
        "summary": summary,
        "body": body,
        "author_user_id": "user_00000000-0000-0000-0000-000000000071",
        "author_player_id": None,
        "author_name": "Me",
        "created_at": NOW,
    }


def test_parse_defaults_type_to_update() -> None:
    request = parse_feed_card(f"---\nsummary: {SUMMARY}\n---\n{BODY}")

    assert request.kind == "update"
    assert request.summary == SUMMARY
    assert request.body == BODY


def test_parse_explicit_type_and_empty_body() -> None:
    request = parse_feed_card("---\ntype: hello\nsummary: Hi there\n---")

    assert request.kind == "hello"
    assert request.summary == "Hi there"
    assert request.body == ""


def test_parse_keeps_colons_and_strips_matching_quotes() -> None:
    colon = parse_feed_card("---\ntype: attention\nsummary: Attention! Need a decision: A or B?\n---\n")
    quoted = parse_feed_card('---\nsummary: "What happened: it is #9 now"\n---\n')

    assert colon.kind == "attention"
    assert colon.summary == "Attention! Need a decision: A or B?"
    assert quoted.summary == "What happened: it is #9 now"


def test_parse_line_without_colon_raises() -> None:
    with pytest.raises(ValueError, match="key: value"):
        parse_feed_card("---\nsummary\n---\n")


def test_parse_missing_summary_raises() -> None:
    with pytest.raises(ValidationError, match="summary"):
        parse_feed_card("---\ntype: attention\n---\nbody\n")


def test_parse_unknown_type_raises() -> None:
    with pytest.raises(ValidationError, match="type"):
        parse_feed_card("---\ntype: alert\nsummary: x\n---\n")


def test_parse_without_front_matter_raises() -> None:
    with pytest.raises(ValueError, match="front matter"):
        parse_feed_card("#### Standing\nNo front matter here.\n")


def test_feed_post_sends_parsed_card(httpserver: HTTPServer, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def handler(request: Request) -> Response:
        captured["body"] = json.loads(request.get_data())
        captured["auth"] = request.headers.get("Authorization")
        return Response(json.dumps(_card()), status=201, content_type="application/json")

    httpserver.expect_request("/observatory/v2/coworlds/paintarena/feed-cards", method="POST").respond_with_handler(
        handler
    )
    card_path = tmp_path / "card.md"
    card_path.write_text(CARD_MD, encoding="utf-8")

    result = CliRunner().invoke(
        app, ["feed", "post", str(card_path), "--coworld", "paintarena", "--server", httpserver.url_for("/")]
    )

    assert result.exit_code == 0, result.output
    body = captured["body"]
    assert isinstance(body, dict)
    assert body.pop("idempotency_key")
    assert body == {"kind": "update", "summary": SUMMARY, "body": BODY}
    assert captured["auth"] == "Bearer token"
    assert CARD_ID in result.output
    assert "Kind: update" in result.output
    assert "Created: 2026-10-07T12:00:00+00:00" in result.output
    assert f"Summary: {SUMMARY[:80]}" in result.output


def test_feed_post_warns_on_long_summary(httpserver: HTTPServer, tmp_path: Path) -> None:
    long_summary = "x" * 351
    httpserver.expect_request("/observatory/v2/coworlds/paintarena/feed-cards", method="POST").respond_with_json(
        _card(summary=long_summary), status=201
    )
    card_path = tmp_path / "long.md"
    card_path.write_text(f"---\nsummary: {long_summary}\n---\n", encoding="utf-8")

    result = CliRunner(mix_stderr=False).invoke(
        app, ["feed", "post", str(card_path), "--coworld", "paintarena", "--server", httpserver.url_for("/")]
    )

    assert result.exit_code == 0, result.output
    assert "warning: summary is 351 characters" in result.stderr
    assert f"Summary: {'x' * 80}" in result.stdout


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
        return Response(json.dumps(_card()), status=201, content_type="application/json")

    httpserver.expect_request("/observatory/v2/coworlds/paintarena/feed-cards", method="POST").respond_with_handler(
        handler
    )
    card_path = tmp_path / "card.md"
    card_path.write_text(CARD_MD, encoding="utf-8")
    args = ["feed", "post", str(card_path), "--coworld", "paintarena", "--server", httpserver.url_for("/")]
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

    card_path.write_text(CARD_MD + "\nNew result.\n", encoding="utf-8")
    changed = CliRunner().invoke(app, args)
    assert changed.exit_code == 0, changed.output
    assert (captured[-1]["idempotency_key"] in keys) == (explicit_key is not None)
