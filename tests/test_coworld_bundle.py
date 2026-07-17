from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest
from typer.testing import CliRunner

from coworld.bundle import _github_source_contexts, _pinned_source_url, build_coworld_manifest
from coworld.cli import app

REAL_SUBPROCESS_RUN = subprocess.run


@pytest.fixture(autouse=True)
def _owner_checkout(tmp_path: Path) -> None:
    _init_git_repo(tmp_path, "git@github.com:Metta-AI/unit-test-coworld.git", "main")
    head = _commit_file(tmp_path, "README.md", "# Unit test Coworld\n")
    _git(tmp_path, "update-ref", "refs/remotes/origin/main", head)


def test_build_coworld_manifest_runs_compose_and_writes_hydrated_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    template_path = _write_manifest(
        tmp_path,
        game_image="{{GAME_IMAGE}}",
        player_image="{{PLAYER_IMAGE}}",
        include_version=False,
    )
    output_path = tmp_path / "dist" / "coworld_manifest.json"
    (tmp_path / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
    calls: list[tuple[list[str], dict[str, object]]] = []
    monkeypatch.setattr(
        "coworld.bundle.subprocess.run",
        _fake_docker_run(
            {
                "game": "game-runtime:latest",
                "player": "player-runtime:latest",
                "grader": "ghcr.io/metta-ai/graders-default:latest",
            },
            {
                "game-runtime:latest": "sha256:1111111111112222222222222222222222222222222222222222222222222222",
                "player-runtime:latest": "sha256:aaaaaaaaaaaabbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                "ghcr.io/metta-ai/graders-default:latest": (
                    "sha256:eeeeeeeeeeeefffffffffffffffffffffffffffffffffffffffffffffffffffff"
                ),
            },
            calls,
        ),
    )

    built_manifest_path = build_coworld_manifest(
        tmp_path / "compose.yaml",
        template_path,
        "0.2.0",
        output_path,
    )

    built_manifest = json.loads(built_manifest_path.read_text(encoding="utf-8"))
    assert built_manifest_path == output_path.resolve()
    assert built_manifest["game"]["version"] == "0.2.0"
    assert built_manifest["game"]["runnable"]["image"] == "game-runtime:coworld-111111111111"
    assert built_manifest["player"][0]["image"] == "player-runtime:coworld-aaaaaaaaaaaa"
    assert built_manifest["reporter"] == [{"reporter": "softmax/default@1"}]
    template = json.loads(template_path.read_text(encoding="utf-8"))
    assert "version" not in template["game"]
    assert template["game"]["runnable"]["image"] == "{{GAME_IMAGE}}"
    assert calls == [
        (
            ["docker", "compose", "-f", str(tmp_path / "compose.yaml"), "config", "--format", "json"],
            {"cwd": tmp_path, "check": True, "capture_output": True, "text": True},
        ),
        (
            [
                "docker",
                "compose",
                "-f",
                str(tmp_path / "compose.yaml"),
                "pull",
                "--ignore-buildable",
                "--ignore-pull-failures",
            ],
            {"cwd": tmp_path, "check": True},
        ),
        (
            ["docker", "compose", "-f", str(tmp_path / "compose.yaml"), "build", "--pull"],
            {"cwd": tmp_path, "check": True},
        ),
        (
            ["docker", "image", "inspect", "--format", "{{.Id}}", "game-runtime:latest"],
            {"check": True, "capture_output": True, "text": True},
        ),
        (
            ["docker", "tag", "game-runtime:latest", "game-runtime:coworld-111111111111"],
            {"check": True},
        ),
        (
            ["docker", "image", "inspect", "--format", "{{.Id}}", "player-runtime:latest"],
            {"check": True, "capture_output": True, "text": True},
        ),
        (
            ["docker", "tag", "player-runtime:latest", "player-runtime:coworld-aaaaaaaaaaaa"],
            {"check": True},
        ),
    ]


def test_build_coworld_manifest_builds_declared_replay_viewer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    template_path = _write_manifest(
        tmp_path,
        game_image="{{GAME_IMAGE}}",
        player_image="{{PLAYER_IMAGE}}",
        include_version=False,
    )
    template = json.loads(template_path.read_text(encoding="utf-8"))
    template["game"]["replay_viewer"] = {"bundle": "replay-viewer"}
    template_path.write_text(json.dumps(template), encoding="utf-8")
    compose_path = tmp_path / "compose.yaml"
    compose_path.write_text("services: {}\n", encoding="utf-8")
    hook = tmp_path / "tools" / "build_replay_viewer.sh"
    hook.parent.mkdir()
    hook.write_text("#!/bin/sh\n", encoding="utf-8")
    hook.chmod(0o755)
    docker_run = _fake_docker_run(
        {
            "game": "game-runtime:latest",
            "player": "player-runtime:latest",
            "grader": "ghcr.io/metta-ai/graders-default:latest",
        },
        {
            "game-runtime:latest": "sha256:111111111111",
            "player-runtime:latest": "sha256:222222222222",
            "ghcr.io/metta-ai/graders-default:latest": "sha256:dddddddddddd",
        },
    )
    hook_calls: list[tuple[list[str], dict[str, object]]] = []

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if command[0] == str(hook):
            output_dir = Path(command[1])
            output_dir.mkdir(parents=True)
            (output_dir / "index.html").write_text("<main>Replay</main>", encoding="utf-8")
            hook_calls.append((command, kwargs))
            return subprocess.CompletedProcess(command, 0)
        return docker_run(command, **kwargs)

    monkeypatch.setattr("coworld.bundle.subprocess.run", run)
    output_path = tmp_path / "dist" / "coworld_manifest.json"

    built_manifest_path = build_coworld_manifest(compose_path, template_path, "0.2.0", output_path)

    built_manifest = json.loads(built_manifest_path.read_text(encoding="utf-8"))
    assert built_manifest["game"]["replay_viewer"] == {"bundle": "replay-viewer"}
    assert (tmp_path / "dist" / "replay-viewer" / "index.html").is_file()
    assert hook_calls == [([str(hook), str(tmp_path / "dist" / "replay-viewer")], {"cwd": tmp_path, "check": True})]


def test_build_coworld_manifest_requires_replay_viewer_build_hook(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    template_path = _write_manifest(
        tmp_path,
        game_image="{{GAME_IMAGE}}",
        player_image="{{PLAYER_IMAGE}}",
        include_version=False,
    )
    template = json.loads(template_path.read_text(encoding="utf-8"))
    template["game"]["replay_viewer"] = {"bundle": "replay-viewer"}
    template_path.write_text(json.dumps(template), encoding="utf-8")
    compose_path = tmp_path / "compose.yaml"
    compose_path.write_text("services: {}\n", encoding="utf-8")
    monkeypatch.setattr(
        "coworld.bundle.subprocess.run",
        _fake_docker_run(
            {
                "game": "game-runtime:latest",
                "player": "player-runtime:latest",
                "grader": "ghcr.io/metta-ai/graders-default:latest",
            },
            {
                "game-runtime:latest": "sha256:111111111111",
                "player-runtime:latest": "sha256:222222222222",
                "ghcr.io/metta-ai/graders-default:latest": "sha256:dddddddddddd",
            },
        ),
    )

    with pytest.raises(RuntimeError, match="executable build hook"):
        build_coworld_manifest(
            compose_path,
            template_path,
            "0.2.0",
            tmp_path / "dist" / "coworld_manifest.json",
        )


def test_build_coworld_manifest_requires_compose_file(tmp_path: Path) -> None:
    template_path = _write_manifest(
        tmp_path,
        game_image="game-runtime:latest",
        player_image="player-runtime:latest",
        include_version=False,
    )

    with pytest.raises(RuntimeError, match="Compose file not found"):
        build_coworld_manifest(tmp_path / "missing-compose.yaml", template_path, "0.2.0", tmp_path / "out.json")


def test_build_coworld_manifest_requires_template_without_version(tmp_path: Path) -> None:
    template_path = _write_manifest(
        tmp_path,
        game_image="game-runtime:latest",
        player_image="player-runtime:latest",
        name="coworld_manifest_template.json",
    )
    (tmp_path / "compose.yaml").write_text("services: {}\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="must not set game.version"):
        build_coworld_manifest(tmp_path / "compose.yaml", template_path, "0.2.0", tmp_path / "out.json")


def test_build_coworld_manifest_tags_primary_role_images(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    template_path = _write_manifest(
        tmp_path,
        game_image="{{GAME_IMAGE}}",
        player_image="{{PLAYER_IMAGE}}",
        include_version=False,
        role_images={
            "commissioner": "{{COMMISSIONER_IMAGE}}",
            "grader": "{{GRADER_IMAGE}}",
            "optimizer": "{{OPTIMIZER_IMAGE}}",
        },
    )
    (tmp_path / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
    monkeypatch.setattr(
        "coworld.bundle.subprocess.run",
        _fake_docker_run(
            {
                "game": "game-runtime:latest",
                "player": "player-runtime:latest",
                "commissioner": "commissioner-runtime:latest",
                "grader": "grader-runtime:latest",
                "optimizer": "optimizer-runtime:latest",
            },
            {
                "game-runtime:latest": "sha256:111111111111",
                "player-runtime:latest": "sha256:222222222222",
                "commissioner-runtime:latest": "sha256:333333333333",
                "grader-runtime:latest": "sha256:555555555555",
                "optimizer-runtime:latest": "sha256:666666666666",
            },
        ),
    )

    output_path = build_coworld_manifest(tmp_path / "compose.yaml", template_path, "0.2.0", tmp_path / "out.json")

    built_manifest = json.loads(output_path.read_text(encoding="utf-8"))
    assert built_manifest["game"]["runnable"]["image"] == "game-runtime:coworld-111111111111"
    assert built_manifest["player"][0]["image"] == "player-runtime:coworld-222222222222"
    assert built_manifest["commissioner"][0]["image"] == "commissioner-runtime:coworld-333333333333"
    assert built_manifest["grader"][0]["image"] == "grader-runtime:coworld-555555555555"
    assert built_manifest["optimizer"][0]["image"] == "optimizer-runtime:coworld-666666666666"


def test_build_coworld_manifest_preserves_digest_pinned_image_refs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    template_path = _write_manifest(
        tmp_path,
        game_image="game-runtime:latest@sha256:1111",
        player_image="player-runtime:latest@sha256:2222",
        include_version=False,
    )
    (tmp_path / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
    calls: list[tuple[list[str], dict[str, object]]] = []
    monkeypatch.setattr(
        "coworld.bundle.subprocess.run",
        _fake_docker_run(
            {
                "game": "game-runtime:latest",
                "player": "player-runtime:latest",
                "grader": "ghcr.io/metta-ai/graders-default:latest",
            },
            {
                "game-runtime:latest@sha256:1111": "sha256:111111111111",
                "player-runtime:latest@sha256:2222": "sha256:222222222222",
                "ghcr.io/metta-ai/graders-default:latest": "sha256:dddddddddddd",
            },
            calls,
        ),
    )

    output_path = build_coworld_manifest(tmp_path / "compose.yaml", template_path, "0.2.0", tmp_path / "out.json")

    built_manifest = json.loads(output_path.read_text(encoding="utf-8"))
    assert built_manifest["game"]["runnable"]["image"] == "game-runtime:latest@sha256:1111"
    assert built_manifest["player"][0]["image"] == "player-runtime:latest@sha256:2222"
    commands = [command for command, _kwargs in calls]
    assert ["docker", "image", "inspect", "--format", "{{.Id}}", "game-runtime:latest@sha256:1111"] not in commands
    assert ["docker", "tag", "game-runtime:latest@sha256:1111", "game-runtime:coworld-111111111111"] not in commands
    assert ["docker", "image", "inspect", "--format", "{{.Id}}", "player-runtime:latest@sha256:2222"] not in commands
    assert ["docker", "tag", "player-runtime:latest@sha256:2222", "player-runtime:coworld-222222222222"] not in commands


def test_build_coworld_manifest_resolves_mutable_registry_image_refs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    template_path = _write_manifest(
        tmp_path,
        game_image="{{GAME_IMAGE}}",
        player_image="{{PLAYER_IMAGE}}",
        include_version=False,
        role_images={
            "commissioner": "{{COMMISSIONER_IMAGE}}",
            "grader": "ghcr.io/metta-ai/graders-default:latest",
        },
    )
    (tmp_path / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
    calls: list[tuple[list[str], dict[str, object]]] = []
    monkeypatch.setattr(
        "coworld.bundle.subprocess.run",
        _fake_docker_run(
            {
                "game": "game-runtime:latest",
                "player": "player-runtime:latest",
                "commissioner": "ghcr.io/metta-ai/commissioners-default:latest",
                "grader": "grader-runtime:latest",
            },
            {
                "game-runtime:latest": "sha256:111111111111",
                "player-runtime:latest": "sha256:222222222222",
                "ghcr.io/metta-ai/commissioners-default:latest": "sha256:333333333333",
                "ghcr.io/metta-ai/graders-default:latest": "sha256:444444444444",
            },
            calls,
            service_platforms={
                "game": "linux/amd64",
                "player": "linux/amd64",
                "commissioner": "linux/amd64",
                "grader": "linux/amd64",
            },
        ),
    )

    output_path = build_coworld_manifest(
        tmp_path / "compose.yaml",
        template_path,
        "0.2.0",
        tmp_path / "out.json",
    )

    built_manifest = json.loads(output_path.read_text(encoding="utf-8"))
    assert built_manifest["game"]["runnable"]["image"] == "game-runtime:coworld-111111111111"
    assert built_manifest["player"][0]["image"] == "player-runtime:coworld-222222222222"
    assert built_manifest["commissioner"][0]["image"] == "ghcr.io/metta-ai/commissioners-default@sha256:333333333333"
    assert built_manifest["grader"][0]["image"] == "ghcr.io/metta-ai/graders-default@sha256:444444444444"
    commands = [command for command, _kwargs in calls]
    assert [
        "docker",
        "buildx",
        "imagetools",
        "inspect",
        "ghcr.io/metta-ai/commissioners-default:latest",
        "--format",
        "{{json .Manifest}}",
    ] in commands
    assert [
        "docker",
        "pull",
        "--platform",
        "linux/amd64",
        "ghcr.io/metta-ai/commissioners-default@sha256:333333333333",
    ] in commands
    assert [
        "docker",
        "pull",
        "--platform",
        "linux/amd64",
        "ghcr.io/metta-ai/graders-default@sha256:444444444444",
    ] in commands


def test_source_url_pinning_uses_checked_out_source_contexts(tmp_path: Path) -> None:
    game_context = tmp_path / "example-game"
    _init_git_repo(game_context, "git@github.com:Metta-AI/example-game.git", "master")
    game_base = _commit_file(game_context, "game.txt", "base\n")
    _git(game_context, "update-ref", "refs/remotes/origin/master", game_base)
    game_head = _commit_file(game_context, "game.txt", "head\n")

    commissioner_context = tmp_path / "coworld-tools"
    _init_git_repo(commissioner_context, "https://github.com/Metta-AI/coworld-tools.git", "main")
    commissioner_stale_head = _commit_file(commissioner_context, "commissioner.txt", "base\n")
    commissioner_main = _commit_file(commissioner_context, "commissioner.txt", "head\n")
    _git(commissioner_context, "update-ref", "refs/remotes/origin/main", commissioner_main)
    _git(commissioner_context, "switch", "-c", "stale", commissioner_stale_head)

    contexts = _github_source_contexts((game_context, commissioner_context))

    assert (
        _pinned_source_url("https://github.com/Metta-AI/example-game/tree/master/players/reference", contexts)
        == f"https://github.com/Metta-AI/example-game/tree/{game_head}/players/reference"
    )
    assert (
        _pinned_source_url(
            "https://github.com/Metta-AI/coworld-tools/tree/main/commissioners/commissioners/default", contexts
        )
        == f"https://github.com/Metta-AI/coworld-tools/tree/{commissioner_main}/commissioners/commissioners/default"
    )


def test_build_command_writes_hydrated_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_manifest(
        tmp_path,
        game_image="game-runtime:latest",
        player_image="player-runtime:latest",
        include_version=False,
    )
    (tmp_path / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
    monkeypatch.setattr(
        "coworld.bundle.subprocess.run",
        _fake_docker_run(
            {
                "game": "game-runtime:latest",
                "player": "player-runtime:latest",
                "grader": "ghcr.io/metta-ai/graders-default:latest",
            },
            {
                "game-runtime:latest": "sha256:111111111111",
                "player-runtime:latest": "sha256:222222222222",
                "ghcr.io/metta-ai/graders-default:latest": "sha256:dddddddddddd",
            },
        ),
    )

    output_path = tmp_path / "dist" / "coworld_manifest.json"
    result = CliRunner().invoke(
        app,
        ["build", "--project", str(tmp_path), "--version", "0.2.0"],
        env={"DOCKER_CONTEXT": "desktop-linux", "DOCKER_HOST": ""},
    )

    assert result.exit_code == 0, result.output
    assert "Docker context: desktop-linux" in result.output
    assert f"Built Coworld manifest: {output_path.resolve()}" in result.output
    built_manifest = json.loads(output_path.read_text(encoding="utf-8"))
    assert built_manifest["game"]["version"] == "0.2.0"
    assert built_manifest["game"]["runnable"]["image"] == "game-runtime:coworld-111111111111"
    assert built_manifest["player"][0]["image"] == "player-runtime:coworld-222222222222"


def _write_manifest(
    base_dir: Path,
    *,
    game_image: str,
    player_image: str,
    name: str = "coworld_manifest_template.json",
    player_id: str = "unit-test-player",
    role_images: Mapping[str, str] | None = None,
    include_version: bool = True,
) -> Path:
    base_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = base_dir / name
    declared_roles = {
        role: [
            {
                "id": f"unit-test-{role}",
                "name": f"unit-test-{role}",
                "type": role,
                "image": image,
                "description": f"Unit test {role}.",
            }
        ]
        for role, image in (role_images or {}).items()
    }
    manifest_path.write_text(
        json.dumps(
            {
                "tags": ["test", "multiplayer", "real-time"],
                "game": {
                    "name": "unit-test-game",
                    **({"version": "0.1.0"} if include_version else {}),
                    "description": "Unit test Coworld.",
                    "owner": "coworld@softmax.com",
                    "runnable": {"type": "game", "image": game_image},
                    "config_schema": {
                        "$schema": "https://json-schema.org/draft/2020-12/schema",
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["tokens"],
                        "properties": {
                            "tokens": {
                                "type": "array",
                                "minItems": 1,
                                "maxItems": 1,
                                "items": {"type": "string"},
                            }
                        },
                    },
                    "results_schema": {
                        "$schema": "https://json-schema.org/draft/2020-12/schema",
                        "type": "object",
                        "required": ["scores"],
                        "properties": {"scores": {"type": "array", "items": {"type": "number"}}},
                    },
                    "protocols": {
                        "player": {"type": "uri", "value": "https://example.com/player_protocol_spec.md"},
                        "global": {"type": "uri", "value": "https://example.com/global_protocol_spec.md"},
                    },
                    "docs": {
                        "readme": {"type": "uri", "value": "https://example.com/README.md"},
                        "pages": [
                            {
                                "id": "rules.md",
                                "title": "rules.md",
                                "content": {"type": "text", "value": "# Rules\n\nScore one point."},
                            },
                            {
                                "id": "play_unittest.md",
                                "title": "play_unittest.md",
                                "content": {"type": "uri", "value": "https://example.com/play_unittest.md"},
                            },
                        ],
                    },
                },
                "player": [
                    {
                        "id": player_id,
                        "name": player_id,
                        "type": "player",
                        "image": player_image,
                        "description": "Unit test player.",
                    }
                ],
                # Reporters are references (spec 0061), untouched by compose hydration.
                "reporter": [{"reporter": "softmax/default@1"}],
                # Default stub; tests override via role_images.
                "grader": [
                    {
                        "id": "unit-test-default-grader",
                        "name": "Unit Test Default Grader",
                        "type": "grader",
                        "image": (
                            "ghcr.io/metta-ai/graders-default@sha256:"
                            "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
                        ),
                        "source_url": "https://github.com/Metta-AI/coworld-tools/tree/e6b7863c2619d260bb29f14364baf09c578c9f30/graders/graders/default/default_grader",
                        "description": "Default grader stub.",
                    }
                ],
                **declared_roles,
                "variants": [
                    {
                        "id": "default",
                        "name": "Default",
                        "description": "Default test variant.",
                        "game_config": {},
                    }
                ],
                "certification": {"game_config": {}, "players": [{"player_id": player_id}]},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return manifest_path


def _init_git_repo(path: Path, remote_url: str, branch: str) -> None:
    path.mkdir(exist_ok=True)
    _git(path, "init", "-b", branch)
    _git(path, "config", "user.email", "coworld-test@example.com")
    _git(path, "config", "user.name", "Coworld Test")
    _git(path, "remote", "add", "origin", remote_url)


def _commit_file(repo: Path, filename: str, content: str) -> str:
    (repo / filename).write_text(content, encoding="utf-8")
    _git(repo, "add", filename)
    _git(repo, "commit", "-m", f"Update {filename}")
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def _fake_docker_run(
    service_images: Mapping[str, str],
    image_ids: Mapping[str, str],
    calls: list[tuple[list[str], dict[str, object]]] | None = None,
    service_platforms: Mapping[str, str] | None = None,
) -> Callable[..., subprocess.CompletedProcess[str]]:
    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if command[0] == "git":
            return REAL_SUBPROCESS_RUN(command, **kwargs)
        if calls is not None:
            calls.append((command, kwargs))
        if command[:3] == ["docker", "compose", "-f"] and command[-3:] == ["config", "--format", "json"]:
            services = {service: {"image": image} for service, image in service_images.items()}
            for service, platform in (service_platforms or {}).items():
                services[service]["platform"] = platform
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps({"services": services}))
        if command[:4] == ["docker", "buildx", "imagetools", "inspect"]:
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps({"digest": image_ids[command[4]]}))
        if command[:3] == ["docker", "image", "inspect"]:
            return subprocess.CompletedProcess(command, 0, stdout=f"{image_ids[command[-1]]}\n")
        return subprocess.CompletedProcess(command, 0)

    return fake_run
