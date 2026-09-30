from importlib.resources import files

import pytest
from typer.testing import CliRunner

from coworld.cli import app


def test_local_docs_list_and_read_without_network(monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("Local documentation reached the network")

    monkeypatch.setattr("softmax.docs_cli.httpx.get", unexpected)
    listing = CliRunner().invoke(app, ["docs", "--local"])
    assert listing.exit_code == 0, listing.output
    assert "COOKBOOK.md" in listing.output.splitlines()
    assert "roles/PLAYER.md" in listing.output.splitlines()
    for name in ("COOKBOOK", "COOKBOOK.md", "roles/PLAYER", "roles/PLAYER.md"):
        result = CliRunner().invoke(app, ["docs", "--local", name])
        assert result.exit_code == 0, result.output
        assert result.output == files("coworld").joinpath("docs", name.removesuffix(".md") + ".md").read_text(
            encoding="utf-8"
        )


@pytest.mark.parametrize(
    "args", [["--skill"], ["../README.md"], ["/README.md"], ["missing.md"], ["roles"], ["README.md?x"]]
)
def test_local_docs_rejects_invalid_requests(args):
    result = CliRunner().invoke(app, ["docs", "--local", *args])
    assert result.exit_code == 2


def test_local_docs_rejects_escaping_symlink(monkeypatch, tmp_path):
    root = tmp_path / "coworld"
    (root / "docs").mkdir(parents=True)
    outside = tmp_path / "private.md"
    outside.write_text("private")
    (root / "docs" / "escape.md").symlink_to(outside)
    monkeypatch.setattr("coworld.cli.files", lambda _: root)
    result = CliRunner().invoke(app, ["docs", "--local", "escape.md"])
    assert result.exit_code == 2
    assert "private" not in result.output


def test_coworld_online_docs_use_shared_fetch(monkeypatch):
    def fetch(path, *, skill, cli):
        assert (path, skill, cli) == ("coworld/cli", False, "coworld")
        return "# CLI\n"

    monkeypatch.setattr("coworld.cli.fetch_docs", fetch)
    result = CliRunner().invoke(app, ["docs", "coworld/cli"])
    assert result.exit_code == 0, result.output
    assert result.output == "# CLI\n"


@pytest.mark.parametrize("name", ["GUIDE", "GUIDE.md"])
def test_local_docs_accepts_declared_package_runfiles(monkeypatch, tmp_path, name):
    installed = tmp_path / "installed" / "coworld"
    (installed / "docs").mkdir(parents=True)
    (installed / "__init__.py").write_text("")
    (installed / "docs" / "GUIDE.md").write_text("# Installed guide\n")
    (installed / "docs" / "undeclared.md").write_text("not declared")
    runfiles = tmp_path / "runfiles" / "coworld"
    (runfiles / "docs").mkdir(parents=True)
    (runfiles / "__init__.py").symlink_to(installed / "__init__.py")
    (runfiles / "docs" / "GUIDE.md").symlink_to(installed / "docs" / "GUIDE.md")
    outside = tmp_path / "private.md"
    outside.write_text("private")
    (runfiles / "docs" / "escape.md").symlink_to(outside)
    monkeypatch.setattr("coworld.cli.files", lambda _: runfiles)
    result = CliRunner().invoke(app, ["docs", "--local", name])
    assert result.exit_code == 0, result.output
    assert result.output == "# Installed guide\n"
    for forbidden in ("escape.md", "missing.md", "undeclared.md"):
        result = CliRunner().invoke(app, ["docs", "--local", forbidden])
        assert result.exit_code == 2
        assert "private" not in result.output
        assert "not declared" not in result.output
