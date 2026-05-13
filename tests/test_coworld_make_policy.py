from pathlib import Path

from typer.testing import CliRunner

from coworld.cli import app


def test_make_policy_writes_among_them_template(tmp_path: Path) -> None:
    output = tmp_path / "amongthem_policy.py"

    result = CliRunner().invoke(app, ["make-policy", "among_them", "-o", str(output)])

    assert result.exit_code == 0, result.output
    assert "Among Them starter policy copied" in result.output
    assert "amongthem_policy.AmongThemPolicy" in result.output
    template = output.read_text(encoding="utf-8")
    assert "class AmongThemPolicy" in template
    assert "coworld make-policy among_them" in template
    assert "cogames upload" not in template
    assert "cogames ship" not in template


def test_make_policy_accepts_among_them_alias(tmp_path: Path) -> None:
    output = tmp_path / "amongthem_policy.py"

    result = CliRunner().invoke(app, ["make-policy", "among-them", "-o", str(output)])

    assert result.exit_code == 0, result.output
    assert output.exists()


def test_make_policy_rejects_non_importable_filename(tmp_path: Path) -> None:
    output = tmp_path / "123-policy.py"

    result = CliRunner().invoke(app, ["make-policy", "among_them", "-o", str(output)])

    assert result.exit_code == 1
    assert "not importable as a Python module" in result.output
