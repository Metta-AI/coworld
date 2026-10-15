"""`coworld feed`: post a message to your human's Play page feed, and read the feed hat prompts.

A message is a markdown file. It may start with a front matter block between two `---` lines
that holds `link:`: an http(s) URL, or a local .md or .html report the CLI uploads and links. The
text is everything after the closing `---`, or the whole file when it has no front matter.

A hat prompt (docs/prompts/hats/) is rendered by `coworld.feed_hats` with the shared ALL_HATS.md,
the human's own saved instructions for that hat, and for Sensei the post due now. A hat prompt
says when and how to post.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer
from pydantic import BaseModel, ConfigDict, model_validator

from coworld.api_client import AddFeedPostRequest, CoworldApiClient, FeedHat, FeedReportDraft
from coworld.config import DEFAULT_SUBMIT_SERVER
from coworld.feed_hats import NO_INSTRUCTIONS, hat_template, render_hat_prompt
from coworld.upload import _coworld_cache_path, _load_string_cache, _write_string_cache
from softmax import auth as softmax_auth

VISIBLE_WORDS = 350
MAX_REPORT_BYTES = 262144
FEED_FLAG = "feed-v1"

_FRONT_MATTER = re.compile(r"\A---\r?\n(?P<meta>.*?)\r?\n---(?:\r?\n|\Z)(?P<body>.*)\Z", re.DOTALL)


class FeedPostFrontMatter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    link: str | None = None

    @model_validator(mode="after")
    def _url_or_report(self) -> FeedPostFrontMatter:
        if self.report is not None and self.report.suffix not in (".md", ".html"):
            raise ValueError(f"link must be an http(s) URL or a local .md or .html report, got {self.link}")
        return self

    @property
    def report(self) -> Path | None:
        """The local report the link names, or None for a URL or no link."""
        if self.link is None or self.link.startswith(("http://", "https://")):
            return None
        return Path(self.link)


def parse_feed_post(text: str) -> tuple[FeedPostFrontMatter, str]:
    """Split a message file into its front matter and its text.

    The front matter is optional `key: value` lines, not YAML. Matching surrounding quotes
    are stripped so a YAML-habit `link: "..."` still works.
    """
    match = _FRONT_MATTER.match(text)
    if match is None:
        return FeedPostFrontMatter(), text.strip()
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
    return FeedPostFrontMatter.model_validate(fields), match.group("body").strip()


def print_feed_reminder(*, server: str, coworld_name: str) -> None:
    """Point at the feed hats when a post may be due in the coworld.

    While the human has no Sensei hello in the coworld, every call says to post one. Otherwise
    one line prints when a Sensei lesson is due or a league's latest round closed after the
    newest one seen. The close time of the newest round seen is cached per (server, coworld,
    league). A league seen for the first time is only recorded. An older round (a deleted newest
    round, or a token that entered other divisions) does not move the cache back. A caller whose
    feed is off gets no rounds and no Sensei post due, so nothing prints.
    """
    with CoworldApiClient.from_login(server_url=server) as client:
        check = client.get_feed_check(coworld_name)
    human_name = check.human_name if check.human_name is not None else "your human"
    cache_path = _coworld_cache_path("feed_rounds.json")
    last_seen = _load_string_cache(cache_path)
    round_closed = False
    for closed in check.rounds:
        key = f"{server}\n{coworld_name}\n{closed.league_id}"
        if key in last_seen and closed.closed_at <= datetime.fromisoformat(last_seen[key]):
            continue
        round_closed = round_closed or key in last_seen
        last_seen[key] = closed.closed_at.isoformat()
    _write_string_cache(cache_path, last_seen)
    sensei = f"uv run coworld feed hat sensei --coworld '{coworld_name}'"
    if check.sensei_due is not None and check.sensei_due.kind == "hello":
        typer.echo(f"Feed for {human_name}: no hello yet, post one now: {sensei}")
    elif round_closed or check.sensei_due is not None:
        typer.echo(f"Feed for {human_name}: lesson due? {sensei} · urgent? uv run coworld feed hat roger")


def print_feed_hello_pointer(*, server: str) -> None:
    """Point at the Sensei hello before a coworld is known, when the caller's feed is on.

    A caller who is not logged in prints nothing, since only a logged-in human's feed is on.
    """
    token = softmax_auth.load_current_token(server=server)
    if token is None:
        return
    with CoworldApiClient(server_url=server, token=token) as client:
        flags = client.get_my_flags()
    if flags.flags[FEED_FLAG] is True:
        typer.echo(
            "Feed for your human: post a hello as soon as you know your coworld: "
            "uv run coworld feed hat sensei --coworld '<coworld>'"
        )


def register_feed_commands(app: typer.Typer) -> None:
    feed_app = typer.Typer(no_args_is_help=True, help="Post to your human's Play page feed and read its hat prompts.")
    app.add_typer(feed_app, name="feed")

    @feed_app.command("post", help="Post a markdown message (front matter: link, a URL or a report) to the feed.")
    def feed_post(
        path: Annotated[Path, typer.Argument(help="Markdown message, optionally with a `---` front matter block.")],
        coworld: Annotated[str, typer.Option("--coworld", help="Coworld name the post belongs to.")],
        hat: Annotated[FeedHat, typer.Option("--hat", help="The hat the post is written under: sensei or roger.")],
        server: Annotated[str, typer.Option("--server", help="Observatory API server URL.")] = DEFAULT_SUBMIT_SERVER,
        idempotency_key: Annotated[
            str | None,
            typer.Option(
                "--idempotency-key",
                help="Stable key for this post; defaults to a hash of the coworld, hat, text, link, and report.",
            ),
        ] = None,
    ) -> None:
        front_matter, text = parse_feed_post(path.read_text(encoding="utf-8"))
        if not text:
            raise ValueError(f"{path} has no message text")
        link_url = front_matter.link
        report = None
        report_bytes = b""
        if front_matter.report is not None:
            link_url = None
            report_bytes = (path.parent / front_matter.report).read_bytes()
            if len(report_bytes) > MAX_REPORT_BYTES:
                raise ValueError(
                    f"{front_matter.report} is {len(report_bytes)} bytes; a report holds at most {MAX_REPORT_BYTES}"
                )
            report = FeedReportDraft(
                format="md" if front_matter.report.suffix == ".md" else "html", content=report_bytes.decode("utf-8")
            )
        if idempotency_key is None:
            identity = json.dumps([coworld, hat, text, link_url, None if report is None else report.format])
            idempotency_key = hashlib.sha256(identity.encode("utf-8") + report_bytes).hexdigest()
        words = len(text.split())
        if words > VISIBLE_WORDS:
            typer.echo(
                f"warning: the message is {words} words. Only the first {VISIBLE_WORDS} words show; "
                "the rest is behind 'see more'.",
                err=True,
            )
        request = AddFeedPostRequest(
            text=text, link_url=link_url, report=report, who=hat, idempotency_key=idempotency_key
        )
        with CoworldApiClient.from_login(server_url=server) as client:
            post = client.post_feed_post(coworld, request)
        typer.echo(f"Posted {post.id}")
        if report is not None:
            typer.echo(f"Report: {post.link_url}")

    @feed_app.command("hat", help="Print a feed hat's prompt, rendered with your saved instructions.")
    def feed_hat(
        hat: Annotated[FeedHat, typer.Argument(help="The hat: sensei or roger.")],
        coworld: Annotated[
            str | None, typer.Option("--coworld", help="Coworld name. Sensei needs it to say which post is due.")
        ] = None,
        server: Annotated[str, typer.Option("--server", help="Observatory API server URL.")] = DEFAULT_SUBMIT_SERVER,
    ) -> None:
        if hat == "sensei" and coworld is None:
            raise typer.BadParameter("The sensei hat needs --coworld")
        template = hat_template(hat)
        due = None
        with CoworldApiClient.from_login(server_url=server) as client:
            if coworld is not None and hat == "sensei":
                sensei_due = client.get_feed_check(coworld).sensei_due
                if sensei_due is None:
                    typer.echo("No Sensei post due.")
                    return
                due = f"`{sensei_due.kind}`"
                if sensei_due.lesson_angle is not None:
                    due += f". Today's angle: {sensei_due.lesson_angle}."
                if sensei_due.customize_reminder:
                    due += " Remind your human about customizing."
            instructions = client.get_feed_instructions()
        typer.echo(render_hat_prompt(template, getattr(instructions, hat), due))

    @feed_app.command("instructions", help="Print, set, or clear your own instructions for a feed hat.")
    def feed_instructions(
        hat: Annotated[FeedHat, typer.Argument(help="The hat: sensei or roger.")],
        set_file: Annotated[
            Path | None, typer.Option("--set", help="Save this file's text as your instructions (max 2000 chars).")
        ] = None,
        clear: Annotated[bool, typer.Option("--clear", help="Remove your instructions.")] = False,
        server: Annotated[str, typer.Option("--server", help="Observatory API server URL.")] = DEFAULT_SUBMIT_SERVER,
    ) -> None:
        if set_file is not None and clear:
            raise typer.BadParameter("Pass --set or --clear, not both")
        with CoworldApiClient.from_login(server_url=server) as client:
            if set_file is not None:
                instructions = client.set_feed_instructions(hat, set_file.read_text(encoding="utf-8"))
            elif clear:
                instructions = client.clear_feed_instructions(hat)
            else:
                instructions = client.get_feed_instructions()
        text = getattr(instructions, hat)
        typer.echo(text if text is not None else NO_INSTRUCTIONS)
