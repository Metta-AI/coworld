from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from coworld.agent_guidance import BEGIN, END, GUIDANCE_BLOCK, find_project_root, update_agent_guidance, upsert_guidance
from coworld.cli import app


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("COWORLD_AGENT_GUIDANCE", raising=False)
    monkeypatch.setattr("coworld.agent_guidance.detect_coding_agent", lambda: "codex")
    monkeypatch.setattr("coworld.cli.active_docker_context", lambda: "test")
    monkeypatch.setattr("softmax.auth.load_current_token", lambda **_: "test")
    monkeypatch.setattr("softmax.auth.load_user_token", lambda **_: "test")
    (tmp_path / ".coworld-project").write_text("player\n")
    return tmp_path


@pytest.mark.parametrize("kind", ["player", "coworld"])
@pytest.mark.parametrize("worktree", [False, True])
def test_nearest_root_stops_at_git_boundary(tmp_path, kind, worktree):
    repo = tmp_path / "repo"
    nested = repo / "project"
    leaf = nested / "src"
    leaf.mkdir(parents=True)
    if worktree:
        (repo / ".git").write_text("gitdir: elsewhere")
    else:
        (repo / ".git").mkdir()
    (tmp_path / ".coworld-project").write_text("coworld")
    assert find_project_root(leaf) is None
    (nested / ".coworld-project").write_text(kind + "\n")
    assert find_project_root(leaf) == nested
    (leaf / ".coworld-project").write_text("player")
    assert find_project_root(leaf) == leaf


def test_non_git_qualification_and_home_rejection(tmp_path, monkeypatch):
    child = tmp_path / "child"
    child.mkdir()
    (tmp_path / ".coworld-project").write_text("coworld")
    assert find_project_root(child) == tmp_path
    (child / "Dockerfile").touch()
    (child / ".coworld-project").write_text("not-player")
    assert find_project_root(child) == tmp_path
    (child / ".coworld-project").write_text("player")
    assert find_project_root(child) == child
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: child))
    assert find_project_root(child) is None

    leaf = child / "scripts"
    leaf.mkdir()
    assert find_project_root(leaf) is None


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


@pytest.mark.parametrize("optout", ["environment", "project", "no-agent"])
def test_optout_precedes_guidance_reads(project, monkeypatch, optout):
    if optout == "environment":
        monkeypatch.setenv("COWORLD_AGENT_GUIDANCE", "0")
        monkeypatch.setattr("coworld.agent_guidance.find_project_root", lambda _: pytest.fail("root lookup"))
    elif optout == "project":
        (project / ".coworld-no-agent-guidance").touch()
    else:
        monkeypatch.setattr("coworld.agent_guidance.detect_coding_agent", lambda: None)
    (project / "AGENTS.md").symlink_to(project / "outside" / "missing")
    update_agent_guidance(project)
    assert (project / "AGENTS.md").is_symlink()


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


COMMANDS = [
    (["build", "--version", "1.0.0"], "coworld.cli.build_coworld_manifest"),
    (["certify", "cow_x"], "coworld.cli.EpisodeArtifacts.create"),
    (["download", "cow_x"], "coworld.cli.download_coworld_cmd"),
    (["play", "cow_x"], "coworld.cli._materialized_manifest_path"),
    (["run-episode", "cow_x"], "coworld.cli._materialized_manifest_path"),
    (["scrimmage", "cow_x", "image"], "coworld.cli._materialized_manifest_path"),
    (["upload-policy", "image"], "coworld.cli.list_players"),
    (["upload-coworld", "manifest.json"], "coworld.upload.upload_coworld"),
    (["submit", "policy:v1", "--league", "league_x"], "coworld.submit.CoworldApiClient.lookup_policy_version"),
]


@pytest.mark.parametrize("args,effect", COMMANDS)
@pytest.mark.parametrize("malformed", [False, True])
def test_every_command_updates_before_effects(project, monkeypatch, args, effect, malformed):
    if malformed:
        (project / "AGENTS.md").write_text(BEGIN)

    def workflow(*args, **kwargs):
        assert not malformed, "Workflow ran despite malformed guidance"
        assert GUIDANCE_BLOCK in (project / "AGENTS.md").read_text()
        raise RuntimeError("workflow reached")

    monkeypatch.setattr(effect, workflow)
    result = CliRunner().invoke(app, args)
    assert result.exit_code != 0
    if malformed:
        assert result.exit_code == 1
        assert "Malformed" in result.output
        assert "Traceback" not in result.output
    else:
        assert "workflow reached" in str(result.exception)


@pytest.mark.parametrize(
    "args",
    [
        ["--help"],
        ["docs", "--local"],
        *[[args[0], "--help"] for args, _ in COMMANDS],
        ["upload-policy"],
        ["upload-policy", "image", "--run", "bad command"],
        ["upload-coworld"],
        ["play", "cow_x", "--aws-region", "us-east-1"],
        ["submit", "policy:v0", "--league", "league_x"],
    ],
)
def test_help_read_only_and_invalid_arguments_do_not_write(project, args):
    CliRunner().invoke(app, args)
    assert not (project / "AGENTS.md").exists()


@pytest.mark.parametrize("newline", [b"\n", b"\r\n"])
def test_inline_marker_mentions_are_preserved(newline):
    prose = b"Remove `" + BEGIN.encode() + b"` through `" + END.encode() + b"`." + newline
    updated = upsert_guidance(prose)
    assert updated.startswith(prose)
    assert upsert_guidance(updated) == updated


@pytest.mark.parametrize("optout_level", ["root", "ancestor", "git", "outside"])
def test_ancestor_optout_stops_at_git_root(project, monkeypatch, optout_level):
    repo = project / "repo"
    root = repo / "area" / "player"
    root.mkdir(parents=True)
    (repo / ".git").write_text("gitdir: elsewhere")
    (root / ".coworld-project").write_text("player")
    optout = {"root": root, "ancestor": root.parent, "git": repo, "outside": project}[optout_level]
    (optout / ".coworld-no-agent-guidance").touch()
    if optout_level != "outside":
        (root / "AGENTS.md").symlink_to(project / "outside.md")
    update_agent_guidance(root)
    if optout_level == "outside":
        assert GUIDANCE_BLOCK in (root / "AGENTS.md").read_text()
    else:
        assert not (project / "outside.md").exists()
        assert (root / "AGENTS.md").is_symlink()


@pytest.mark.parametrize(
    "command,effect",
    [
        ("build", "coworld.cli.build_coworld_manifest"),
        ("upload-coworld", "coworld.upload.upload_coworld"),
        ("certify", "coworld.cli.EpisodeArtifacts.create"),
        ("play", "coworld.cli._materialized_manifest_path"),
        ("run-episode", "coworld.cli._materialized_manifest_path"),
        ("scrimmage", "coworld.cli._materialized_manifest_path"),
    ],
)
def test_commands_use_target_project_instead_of_cwd(project, monkeypatch, command, effect):
    target = project / "target"
    target.mkdir()
    (target / ".coworld-project").write_text("coworld")
    dist = target / "dist"
    dist.mkdir()
    manifest = dist / "coworld_manifest.json"
    manifest.write_text("{}")
    args = [command, str(manifest)]
    if command == "build":
        args = [command, "--project", str(target), "--version", "1.0.0"]
    elif command == "scrimmage":
        args.append("image")

    def workflow(*args, **kwargs):
        assert GUIDANCE_BLOCK in (target / "AGENTS.md").read_text()
        assert not (project / "AGENTS.md").exists()
        assert {p.name for p in dist.iterdir()} == {"coworld_manifest.json"}
        raise RuntimeError("target workflow reached")

    monkeypatch.setattr(effect, workflow)
    result = CliRunner().invoke(app, args)
    assert "target workflow reached" in str(result.exception)


def test_optout_below_project_root_does_not_disable_project(project):
    (project / ".git").mkdir()
    child = project / "src"
    child.mkdir()
    (child / ".coworld-no-agent-guidance").touch()
    update_agent_guidance(child)
    assert GUIDANCE_BLOCK in (project / "AGENTS.md").read_text()


@pytest.mark.parametrize("marker", ["coworld_manifest.json", "coworld_manifest_template.json"])
def test_manifest_only_project_does_not_opt_in(project, marker):
    (project / ".coworld-project").unlink()
    (project / marker).write_text("{}")
    assert find_project_root(project) is None
    update_agent_guidance(project)
    assert not (project / "AGENTS.md").exists()
    assert not (project / "CLAUDE.md").exists()


@pytest.mark.parametrize("git", [False, True])
def test_manifest_directory_uses_explicit_ancestor(project, git):
    package = project / "download"
    leaf = package / "scripts"
    leaf.mkdir(parents=True)
    if git:
        (project / ".git").mkdir()
    (package / "coworld_manifest.json").write_text("{}")
    assert find_project_root(leaf) == project
    (package / ".coworld-project").write_text("coworld")
    assert find_project_root(leaf) == package


def test_non_git_parent_optout_precedes_guidance_reads(project):
    leaf = project / "scripts"
    leaf.mkdir()
    (project / ".coworld-no-agent-guidance").touch()
    (project / "AGENTS.md").symlink_to(project.parent / "outside.md")
    update_agent_guidance(leaf)
    assert (project / "AGENTS.md").is_symlink()


def test_managed_block_points_to_current_guide():
    assert GUIDANCE_BLOCK.splitlines() == [
        BEGIN,
        "Before working in this Coworld project, read https://softmax.com/agents.md "
        "(the Softmax agent guide; it is generated and kept current).",
        "Run `coworld docs` for the documentation index and `coworld docs --local` "
        "for the references installed with the CLI.",
        "Disable these automatic updates with COWORLD_AGENT_GUIDANCE=0 or a .coworld-no-agent-guidance file.",
        END,
    ]
