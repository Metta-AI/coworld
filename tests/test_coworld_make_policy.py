import importlib.resources
from pathlib import Path

from typer.testing import CliRunner

from coworld.cli import app


def test_make_policy_writes_among_them_starter_project(tmp_path: Path) -> None:
    output = tmp_path / "amongthemstarter"

    result = CliRunner().invoke(app, ["make-policy", "among_them", "-o", str(output)])

    assert result.exit_code == 0, result.output
    assert "Among Them starter policy copied" in result.output
    assert "Policy source:" in result.output
    assert "docker build --platform=linux/amd64 -t amongthemstarter:latest" in result.output

    expected_source = (
        importlib.resources.files("coworld.policies").joinpath("amongthemstarter/amongthemstarter.nim").read_bytes()
    )
    assert (output / "amongthemstarter.nim").read_bytes() == expected_source
    assert (output / "README.md").is_file()
    assert (output / ".dockerignore").is_file()

    dockerfile = (output / "Dockerfile").read_text(encoding="utf-8")
    assert "BITWORLD_REF=master" in dockerfile
    assert "COPY --from=build /workspace/bitworld/client/data ./client/data" in dockerfile
    assert 'CMD ["/bin/amongthemstarter", "--address:host.docker.internal", "--port:8080"]' in dockerfile

    source = (output / "amongthemstarter.nim").read_text(encoding="utf-8")
    assert "proc holdTaskAction" in source
    assert "TaskHoldPadding = 8" in source
    assert "starting amongthemstarter" in source


def test_make_policy_accepts_among_them_alias(tmp_path: Path) -> None:
    output = tmp_path / "amongthemstarter"

    result = CliRunner().invoke(app, ["make-policy", "among-them", "-o", str(output)])

    assert result.exit_code == 0, result.output
    assert (output / "amongthemstarter.nim").is_file()


def test_make_policy_rejects_python_file_output(tmp_path: Path) -> None:
    output = tmp_path / "amongthem_policy.py"

    result = CliRunner().invoke(app, ["make-policy", "among_them", "-o", str(output)])

    assert result.exit_code == 1
    assert "output must be a project directory" in result.output


def test_make_policy_allows_project_directory_names_that_are_not_python_modules(tmp_path: Path) -> None:
    output = tmp_path / "123-policy"

    result = CliRunner().invoke(app, ["make-policy", "among_them", "-o", str(output)])

    assert result.exit_code == 0, result.output
    assert (output / "amongthemstarter.nim").is_file()
