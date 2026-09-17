from importlib.resources import files

import pytest
from typer.testing import CliRunner

from coworld.agent_guidance import GUIDANCE_BLOCK, IMPORT_BLOCK
from coworld.cli import app


@pytest.mark.parametrize("target", [".", "empty", "nested/new"])
def test_init_copies_packaged_player_and_explicit_guidance(tmp_path, monkeypatch, target):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("COWORLD_AGENT_GUIDANCE", "0")
    monkeypatch.setattr("coworld.agent_guidance.detect_coding_agent", lambda: None)
    if target == "empty":
        (tmp_path / target).mkdir()
    args = ["init", "player"] + ([] if target == "." else [target])
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.output
    project = tmp_path / target
    template = files("coworld") / "templates" / "roles" / "player"
    for name in ("README.md", "Dockerfile", "player.py"):
        assert (project / name).read_bytes() == (template / name).read_bytes()
    assert {p.name for p in project.iterdir()} == {
        "README.md",
        "Dockerfile",
        "player.py",
        ".coworld-project",
        "AGENTS.md",
        "CLAUDE.md",
    }
    assert (project / ".coworld-project").read_text() == "player\n"
    assert GUIDANCE_BLOCK in (project / "AGENTS.md").read_text()
    assert "[README.md](README.md)" in (project / "AGENTS.md").read_text()
    assert (project / "CLAUDE.md").read_text() == IMPORT_BLOCK + "\n"
    assert "platform-hosted WebSocket skeleton" in result.output
    assert "game-hosted file player" in result.output
    assert "https://softmax.com/docs/coworld/build-a-player/choose-a-coworld" in result.output
    assert "coworld leagues" in result.output
    before = {p.name: p.read_bytes() for p in project.iterdir()}
    assert CliRunner().invoke(app, args).exit_code == 2
    assert before == {p.name: p.read_bytes() for p in project.iterdir()}


@pytest.mark.parametrize("occupied", ["file", "hidden", "directory"])
def test_init_rejects_occupied_target_without_writes(tmp_path, occupied):
    target = tmp_path / "target"
    if occupied == "file":
        target.write_text("keep")
    else:
        target.mkdir()
        if occupied == "hidden":
            (target / ".keep").write_text("keep")
        else:
            (target / "child").mkdir()
    before = sorted(tmp_path.rglob("*"))
    result = CliRunner().invoke(app, ["init", "player", str(target)])
    assert result.exit_code == 2
    assert "missing or empty" in result.output
    assert sorted(tmp_path.rglob("*")) == before
    if occupied == "file":
        assert target.read_text() == "keep"
    elif occupied == "hidden":
        assert (target / ".keep").read_text() == "keep"


def test_init_help_does_not_create_target(tmp_path):
    target = tmp_path / "new"
    result = CliRunner().invoke(app, ["init", "player", str(target), "--help"])
    assert result.exit_code == 0
    assert not target.exists()


@pytest.mark.parametrize("name", ["PLAYER_RUNTIMES.md", "roles/PLAYER.md"])
def test_scaffold_references_are_readable_offline(name):
    result = CliRunner().invoke(app, ["docs", "--local", name])
    assert result.exit_code == 0, result.output
    assert "platform-hosted" in result.output
