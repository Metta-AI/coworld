from __future__ import annotations

import importlib.resources
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class StarterPolicy:
    display_name: str
    package: str
    image_tag: str
    source_file: str
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
        image_tag="amongthemstarter:latest",
        source_file="amongthemstarter.nim",
        project_resources={
            "amongthemstarter/amongthemstarter.nim": "amongthemstarter.nim",
            "amongthemstarter/Dockerfile.amongthemstarter": "Dockerfile",
            "amongthemstarter/.dockerignore": ".dockerignore",
            "amongthemstarter/README.md": "README.md",
        },
    ),
    "cogs_vs_clips": StarterPolicy(
        display_name="Cogs vs Clips",
        package="coworld.policies",
        image_tag="cogs_vs_clips:latest",
        source_file="player.py",
        project_resources={
            "cogs_vs_clips/player.py": "player.py",
            "cogs_vs_clips/Dockerfile.cogs_vs_clips": "Dockerfile",
            "cogs_vs_clips/.dockerignore": ".dockerignore",
            "cogs_vs_clips/README.md": "README.md",
        },
    ),
}


def write_starter_policy(policy: str, output: Path) -> StarterPolicyWriteResult:
    output_path = Path.cwd() / output
    starter = STARTER_POLICIES[policy]
    output_path.mkdir(parents=True, exist_ok=True)
    for resource, target in starter.project_resources.items():
        _write_resource(starter.package, resource, output_path / target)
    return StarterPolicyWriteResult(
        display_name=starter.display_name,
        output_path=output_path,
        source_path=output_path / starter.source_file,
    )


def _write_resource(package: str, resource: str, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    content = importlib.resources.files(package).joinpath(resource).read_bytes()
    output.write_bytes(content)
