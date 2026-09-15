"""Every command must describe itself: the command table is the first thing an agent reads."""

from __future__ import annotations

import click
import typer
import typer.testing
from typer.main import get_command

from coworld.cli import app
from coworld.config import DOCS_AGENT_INDEX_URL, DOCS_AGENT_SKILL_URL, DOCS_PAGES


def _walk(group: click.Group, prefix: tuple[str, ...] = ()) -> list[tuple[tuple[str, ...], click.Command]]:
    found: list[tuple[tuple[str, ...], click.Command]] = []
    for name, command in group.commands.items():
        path = (*prefix, name)
        found.append((path, command))
        if isinstance(command, click.Group):
            found.extend(_walk(command, path))
    return found


def test_every_coworld_command_has_help_text() -> None:
    root = get_command(app)
    assert isinstance(root, click.Group)
    missing = [" ".join(path) for path, command in _walk(root) if not (command.help or "").strip()]
    assert missing == []


def test_workflow_commands_point_at_their_docs_page() -> None:
    root = get_command(app)
    assert isinstance(root, click.Group)
    commands = {" ".join(path): command for path, command in _walk(root)}
    expected = {
        "download": DOCS_PAGES["choose-a-coworld"],
        "upload-policy": DOCS_PAGES["upload-and-evaluate"],
        "submit": DOCS_PAGES["submit-to-a-league"],
        "upload-coworld": DOCS_PAGES["build-certify-upload"],
        "certify": DOCS_PAGES["build-certify-upload"],
        "episode-logs": DOCS_PAGES["debug-hosted-episodes"],
        "leagues": DOCS_PAGES["competition"],
    }
    for name, url in expected.items():
        assert url in (commands[name].epilog or ""), name


def test_root_help_names_the_docs_index_and_skill() -> None:
    result = typer.testing.CliRunner().invoke(app, ["--help"], env={"COLUMNS": "400"})
    assert result.exit_code == 0
    assert DOCS_AGENT_INDEX_URL in result.output
    assert DOCS_AGENT_SKILL_URL in result.output
