from __future__ import annotations

import importlib.resources
import keyword
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StarterPolicy:
    display_name: str
    package: str
    resource: str
    class_name: str


STARTER_POLICIES = {
    "among_them": StarterPolicy(
        display_name="Among Them",
        package="coworld.policies",
        resource="amongthem_policy_template.py",
        class_name="AmongThemPolicy",
    ),
}

STARTER_POLICY_ALIASES = {
    "among_them": "among_them",
    "among-them": "among_them",
    "amongthem": "among_them",
}


def write_starter_policy(policy: str, output: Path) -> tuple[str, str, Path]:
    key = STARTER_POLICY_ALIASES[policy]
    output_path = Path.cwd() / output
    starter = STARTER_POLICIES[key]
    template = importlib.resources.files(starter.package).joinpath(starter.resource).read_text()
    output_path.write_text(template, encoding="utf-8")
    return starter.display_name, starter.class_name, output_path


def policy_module_name_error(path: Path) -> str | None:
    module_name = path.stem
    if not module_name.isidentifier() or keyword.iskeyword(module_name):
        return (
            f"Output filename stem '{module_name}' is not importable as a Python module. "
            "Use letters, numbers, and underscores, and do not start with a number."
        )
    return None
