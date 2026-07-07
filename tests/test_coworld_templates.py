from __future__ import annotations

import json
import tomllib
from pathlib import Path

import coworld

ROLE_TEMPLATE_FILES = {
    "game": {"README.md", "Dockerfile", "game_server.py"},
    "player": {"README.md", "Dockerfile", "player.py"},
    "commissioner": {"README.md", "Dockerfile", "commissioner.py", "commissioner_manifest_entry.json"},
    "grader": {"README.md", "Dockerfile", "grader.py"},
    "diagnoser": {"README.md", "Dockerfile", "diagnoser.py"},
    "optimizer": {"README.md", "optimizer_manifest_entry.json", "optimizer_plan.py"},
}


def test_coworld_templates_include_every_role() -> None:
    template_root = Path(coworld.__file__).parent / "templates"

    assert (template_root / "README.md").is_file()
    for role, filenames in ROLE_TEMPLATE_FILES.items():
        role_root = template_root / "roles" / role
        assert role_root.is_dir()
        assert {path.name for path in role_root.iterdir() if path.is_file()} == filenames


def test_coworld_template_files_are_nonempty_and_json_fragments_parse() -> None:
    template_root = Path(coworld.__file__).parent / "templates"

    for path in template_root.rglob("*"):
        if path.is_file():
            assert path.stat().st_size > 0, path
        if path.suffix == ".json":
            json.loads(path.read_text(encoding="utf-8"))


def test_pyproject_ships_templates_and_complete_paintarena_example() -> None:
    pyproject_path = Path(__file__).parents[1] / "pyproject.toml"
    pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    package_data = pyproject["tool"]["setuptools"]["package-data"]["coworld"]
    excluded = pyproject["tool"]["setuptools"]["exclude-package-data"]["coworld"]

    assert "templates/**/*" in package_data
    assert "examples/**/*" in package_data
    assert "**/Dockerfile" not in excluded
    assert "examples/**/README.md" not in excluded
    assert "examples/**/*_spec.md" not in excluded
