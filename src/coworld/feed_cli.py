"""`coworld feed` — post markdown cards to your human's play-page feed.

A card is a markdown file that starts with a front matter block between two `---` lines:
`summary: <one line of plain text>` (required) and `type: hello | update | attention`
(default update). Everything after the closing `---` is the card body. See
docs/FEED_CARDS.md for the writing rules.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Annotated

import typer
from pydantic import BaseModel

from coworld.api_client import AddFeedCardRequest, CoworldApiClient, FeedCardKind
from coworld.config import DEFAULT_SUBMIT_SERVER

SUMMARY_SOFT_LIMIT = 350

# Printed once by the commands an agent runs at the moments a card may be due (`init player`,
# `upload-policy`, `submit`). A question and a pointer, never an instruction to post: the
# rules in FEED_CARDS.md decide, and they are not repeated here to keep the output small.
FEED_CARD_RULES_POINTER = "Rules: uv run coworld docs --local FEED_CARDS"
FEED_CARD_REMINDER = f"Feed: is it time for a card on your human's play page? {FEED_CARD_RULES_POINTER}"
FEED_CARD_HELLO_REMINDER = f"Feed: say hello on your human's play page with a hello card. {FEED_CARD_RULES_POINTER}"

_FRONT_MATTER = re.compile(r"\A---\r?\n(?P<meta>.*?)\r?\n---(?:\r?\n|\Z)(?P<body>.*)\Z", re.DOTALL)


class FeedCardFrontMatter(BaseModel):
    type: FeedCardKind = "update"
    summary: str


class FeedCardContent(BaseModel):
    kind: FeedCardKind
    summary: str
    body: str


def parse_feed_card(text: str) -> FeedCardContent:
    """Parse the card's content without assigning a request identity.

    The front matter is `key: value` lines, not YAML: a summary is prose and may contain
    colons, quotes, or `#`, none of which should need escaping. Matching surrounding quotes
    are stripped so a YAML-habit `summary: "..."` still works.
    """
    match = _FRONT_MATTER.match(text)
    if match is None:
        raise ValueError("feed card must start with a front matter block delimited by '---' lines")
    fields: dict[str, str] = {}
    for line in match.group("meta").splitlines():
        if not line.strip():
            continue
        key, separator, value = line.partition(":")
        if not separator:
            raise ValueError(f"front matter line must look like `key: value`, got {line!r}")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        fields[key.strip()] = value
    meta = FeedCardFrontMatter.model_validate(fields)
    return FeedCardContent(kind=meta.type, summary=meta.summary, body=match.group("body"))


def register_feed_commands(app: typer.Typer) -> None:
    feed_app = typer.Typer(no_args_is_help=True, help="Post cards to your human's play-page feed.")
    app.add_typer(feed_app, name="feed")

    @feed_app.command("post", help="Post a markdown card (front matter: summary, type) to the feed.")
    def feed_post(
        path: Annotated[Path, typer.Argument(help="Markdown file with a `---` front matter block.")],
        coworld: Annotated[str, typer.Option("--coworld", help="Coworld name the card belongs to.")],
        server: Annotated[str, typer.Option("--server", help="Observatory API server URL.")] = DEFAULT_SUBMIT_SERVER,
        idempotency_key: Annotated[
            str | None,
            typer.Option(
                "--idempotency-key",
                help="Stable key for this post; defaults to a hash of the coworld and card content.",
            ),
        ] = None,
    ) -> None:
        content = parse_feed_card(path.read_text(encoding="utf-8"))
        if idempotency_key is None:
            payload = f"{coworld}\n{content.model_dump_json()}"
            idempotency_key = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        request = AddFeedCardRequest(**content.model_dump(), idempotency_key=idempotency_key)
        if len(request.summary) > SUMMARY_SOFT_LIMIT:
            typer.echo(
                f"warning: summary is {len(request.summary)} characters; the feed card shows at most "
                f"{SUMMARY_SOFT_LIMIT}",
                err=True,
            )
        with CoworldApiClient.from_login(server_url=server) as client:
            card = client.post_feed_card(coworld, request)
        typer.echo(f"Posted feed card {card.id}")
        typer.echo(f"Kind: {card.kind}")
        typer.echo(f"Created: {card.created_at.isoformat()}")
        typer.echo(f"Summary: {card.summary[:80]}")
