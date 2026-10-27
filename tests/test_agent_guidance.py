import pytest
import typer

from coworld.agent_guidance import BEGIN, END, GUIDANCE_BLOCK, update_agent_guidance, upsert_guidance


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("COWORLD_AGENT_GUIDANCE", raising=False)
    monkeypatch.setattr("coworld.agent_guidance.detect_coding_agent", lambda: "codex")
    monkeypatch.setattr("coworld.cli.active_docker_context", lambda: "test")
    monkeypatch.setattr("softmax_client.credentials.load_current_token", lambda **_: "test")
    monkeypatch.setattr("softmax_client.credentials.load_user_token", lambda **_: "test")
    monkeypatch.setattr("coworld.cli.print_feed_hello_pointer", lambda *, server: None)
    (tmp_path / ".coworld-project").write_text("player\n")
    return tmp_path


@pytest.mark.parametrize("newline", [b"\n", b"\r\n"])
def test_upsert_preserves_outside_bytes_and_newlines(newline):
    before, after = b"\xff custom" + newline, newline + b"tail\x80"
    original = before + BEGIN.encode() + newline + b"old" + newline + END.encode() + after
    updated = upsert_guidance(original)
    assert updated == before + GUIDANCE_BLOCK.encode().replace(b"\n", newline) + after
    assert upsert_guidance(updated) == updated


@pytest.mark.parametrize(
    "text", [BEGIN, END, END + "\n" + BEGIN, GUIDANCE_BLOCK + "\n" + GUIDANCE_BLOCK, "prefix" + GUIDANCE_BLOCK]
)
def test_malformed_markers_fail_without_writes(project, text, capsys):
    path = project / "AGENTS.md"
    path.write_text(text)
    with pytest.raises(typer.Exit) as error:
        update_agent_guidance(project)
    assert error.value.exit_code == 1
    assert "Repair" in capsys.readouterr().err
    assert path.read_text() == text


@pytest.mark.parametrize("alias", ["separate", "symlink", "import"])
def test_claude_aliases_imports_and_idempotency(project, monkeypatch, alias):
    monkeypatch.setattr("coworld.agent_guidance.detect_coding_agent", lambda: "claude-code")
    agents, claude = project / "AGENTS.md", project / "CLAUDE.md"
    agents.write_bytes(b"custom\r\n")
    if alias == "symlink":
        claude.symlink_to(agents)
    elif alias == "import":
        claude.write_text("my rules\n@AGENTS.md\n")
    update_agent_guidance(project)
    original = [(p.read_bytes(), p.stat().st_mtime_ns) for p in (agents, claude)]
    update_agent_guidance(project)
    assert original == [(p.read_bytes(), p.stat().st_mtime_ns) for p in (agents, claude)]
    assert agents.read_bytes().startswith(b"custom\r\n")
    assert ("@AGENTS.md" in claude.read_text()) == (alias in {"separate", "import"})


def test_external_symlink_and_malformed_claude_are_rejected_before_writes(
    project, monkeypatch, tmp_path_factory, capsys
):
    monkeypatch.setattr("coworld.agent_guidance.detect_coding_agent", lambda: "claude-code")
    outside = tmp_path_factory.mktemp("external") / "guide.md"
    outside.write_text("untouched")
    claude = project / "CLAUDE.md"
    claude.symlink_to(outside)
    with pytest.raises(typer.Exit):
        update_agent_guidance(project)
    assert not (project / "AGENTS.md").exists()
    assert outside.read_text() == "untouched"
    assert "outside the project" in capsys.readouterr().err
    claude.unlink()
    claude.write_text(BEGIN)
    with pytest.raises(typer.Exit):
        update_agent_guidance(project)
    assert not (project / "AGENTS.md").exists()
