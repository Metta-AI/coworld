from __future__ import annotations

import importlib.resources
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class StarterPolicy:
    display_name: str
    package: str
    project_resources: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class StarterPolicyWriteResult:
    display_name: str
    output_path: Path
    source_path: Path | None = None


STARTER_POLICIES = {
    "among_them": StarterPolicy(
        display_name="Among Them",
        package="coworld.policies",
        project_resources={
            "amongthemstarter/amongthemstarter.nim": "amongthemstarter.nim",
            "amongthemstarter/Dockerfile.amongthemstarter": "Dockerfile",
            "amongthemstarter/.dockerignore": ".dockerignore",
            "amongthemstarter/README.md": "README.md",
        },
    ),
}

STARTER_POLICY_ALIASES = {
    "among_them": "among_them",
    "among-them": "among_them",
    "amongthem": "among_them",
}


def write_starter_policy(policy: str, output: Path) -> StarterPolicyWriteResult:
    key = STARTER_POLICY_ALIASES[policy]
    output_path = Path.cwd() / output
    starter = STARTER_POLICIES[key]
    output_path.mkdir(parents=True, exist_ok=True)
    for resource, target in starter.project_resources.items():
        _write_resource(starter.package, resource, output_path / target)
    return StarterPolicyWriteResult(
        display_name=starter.display_name,
        output_path=output_path,
        source_path=output_path / "amongthemstarter.nim",
    )


def _write_resource(package: str, resource: str, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    content = importlib.resources.files(package).joinpath(resource).read_bytes()
    output.write_bytes(content)
