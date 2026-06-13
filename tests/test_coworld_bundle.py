from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest
from typer.testing import CliRunner

from coworld.bundle import build_coworld_manifest
from coworld.cli import app


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
                "reporter": "ghcr.io/metta-ai/reporters-default:latest",
                "grader": "ghcr.io/metta-ai/graders-default:latest",
            },
            {
                "game-runtime:latest": "sha256:1111111111112222222222222222222222222222222222222222222222222222",
                "player-runtime:latest": "sha256:aaaaaaaaaaaabbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                "ghcr.io/metta-ai/reporters-default:latest": (
                    "sha256:ccccccccccccddddddddddddddddddddddddddddddddddddddddddddddddddddd"
                ),
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
            ["docker", "compose", "-f", str(tmp_path / "compose.yaml"), "build"],
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
        (
            [
                "docker",
                "image",
                "inspect",
                "--format",
                "{{.Id}}",
                "ghcr.io/metta-ai/reporters-default:latest",
            ],
            {"check": True, "capture_output": True, "text": True},
        ),
        (
            [
                "docker",
                "tag",
                "ghcr.io/metta-ai/reporters-default:latest",
                "ghcr.io/metta-ai/reporters-default:coworld-cccccccccccc",
            ],
            {"check": True},
        ),
        (
            [
                "docker",
                "image",
                "inspect",
                "--format",
                "{{.Id}}",
                "ghcr.io/metta-ai/graders-default:latest",
            ],
            {"check": True, "capture_output": True, "text": True},
        ),
        (
            [
                "docker",
                "tag",
                "ghcr.io/metta-ai/graders-default:latest",
                "ghcr.io/metta-ai/graders-default:coworld-eeeeeeeeeeee",
            ],
            {"check": True},
        ),
    ]


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


def test_build_coworld_manifest_overrides_source_manifest_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path = _write_manifest(
        tmp_path,
        game_image="{{GAME_IMAGE}}",
        player_image="{{PLAYER_IMAGE}}",
        name="coworld_manifest.json",
    )
    (tmp_path / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
    monkeypatch.setattr(
        "coworld.bundle.subprocess.run",
        _fake_docker_run(
            {
                "game": "game-runtime:latest",
                "player": "player-runtime:latest",
                "reporter": "ghcr.io/metta-ai/reporters-default:latest",
                "grader": "ghcr.io/metta-ai/graders-default:latest",
            },
            {
                "game-runtime:latest": "sha256:111111111111",
                "player-runtime:latest": "sha256:222222222222",
                "ghcr.io/metta-ai/reporters-default:latest": "sha256:333333333333",
                "ghcr.io/metta-ai/graders-default:latest": "sha256:444444444444",
            },
        ),
    )

    output_path = build_coworld_manifest(tmp_path / "compose.yaml", manifest_path, "0.2.0", tmp_path / "out.json")

    built_manifest = json.loads(output_path.read_text(encoding="utf-8"))
    source_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert source_manifest["game"]["version"] == "0.1.0"
    assert built_manifest["game"]["version"] == "0.2.0"


def test_build_coworld_manifest_tags_primary_role_images(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    template_path = _write_manifest(
        tmp_path,
        game_image="{{GAME_IMAGE}}",
        player_image="{{PLAYER_IMAGE}}",
        include_version=False,
        role_images={
            "commissioner": "{{COMMISSIONER_IMAGE}}",
            "reporter": "{{REPORTER_IMAGE}}",
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
                "reporter": "reporter-runtime:latest",
                "grader": "grader-runtime:latest",
                "optimizer": "optimizer-runtime:latest",
            },
            {
                "game-runtime:latest": "sha256:111111111111",
                "player-runtime:latest": "sha256:222222222222",
                "commissioner-runtime:latest": "sha256:333333333333",
                "reporter-runtime:latest": "sha256:444444444444",
                "grader-runtime:latest": "sha256:555555555555",
                "optimizer-runtime:latest": "sha256:666666666666",
                # Defensive: stub reporter is overridden by role_images here, but keep mock entry
                # in case a future refactor regresses the override.
                "ghcr.io/metta-ai/reporters-default:latest": "sha256:777777777777",
            },
        ),
    )

    output_path = build_coworld_manifest(tmp_path / "compose.yaml", template_path, "0.2.0", tmp_path / "out.json")

    built_manifest = json.loads(output_path.read_text(encoding="utf-8"))
    assert built_manifest["game"]["runnable"]["image"] == "game-runtime:coworld-111111111111"
    assert built_manifest["player"][0]["image"] == "player-runtime:coworld-222222222222"
    assert built_manifest["commissioner"][0]["image"] == "commissioner-runtime:coworld-333333333333"
    assert built_manifest["reporter"][0]["image"] == "reporter-runtime:coworld-444444444444"
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
                "reporter": "ghcr.io/metta-ai/reporters-default:latest",
                "grader": "ghcr.io/metta-ai/graders-default:latest",
            },
            {
                "game-runtime:latest@sha256:1111": "sha256:111111111111",
                "player-runtime:latest@sha256:2222": "sha256:222222222222",
                "ghcr.io/metta-ai/reporters-default:latest": "sha256:cccccccccccc",
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
            "reporter": "{{REPORTER_IMAGE}}",
            "grader": "{{GRADER_IMAGE}}",
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
                "reporter": "ghcr.io/metta-ai/reporters-default@sha256:cccc",
                "grader": "ghcr.io/metta-ai/graders-default@sha256:dddd",
            },
            {
                "game-runtime:latest": "sha256:111111111111",
                "player-runtime:latest": "sha256:222222222222",
                "ghcr.io/metta-ai/commissioners-default:latest": "sha256:333333333333",
            },
            calls,
        ),
    )

    output_path = build_coworld_manifest(
        tmp_path / "compose.yaml",
        template_path,
        "0.2.0",
        tmp_path / "out.json",
        resolve_mutable_image_refs=True,
    )

    built_manifest = json.loads(output_path.read_text(encoding="utf-8"))
    assert built_manifest["game"]["runnable"]["image"] == "game-runtime:coworld-111111111111"
    assert built_manifest["player"][0]["image"] == "player-runtime:coworld-222222222222"
    assert built_manifest["commissioner"][0]["image"] == "ghcr.io/metta-ai/commissioners-default@sha256:333333333333"
    assert built_manifest["reporter"][0]["image"] == "ghcr.io/metta-ai/reporters-default@sha256:cccc"
    assert built_manifest["grader"][0]["image"] == "ghcr.io/metta-ai/graders-default@sha256:dddd"
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
    assert ["docker", "pull", "ghcr.io/metta-ai/commissioners-default@sha256:333333333333"] in commands


def test_build_command_writes_hydrated_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    template_path = _write_manifest(
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
                "reporter": "ghcr.io/metta-ai/reporters-default:latest",
                "grader": "ghcr.io/metta-ai/graders-default:latest",
            },
            {
                "game-runtime:latest": "sha256:111111111111",
                "player-runtime:latest": "sha256:222222222222",
                "ghcr.io/metta-ai/reporters-default:latest": "sha256:cccccccccccc",
                "ghcr.io/metta-ai/graders-default:latest": "sha256:dddddddddddd",
            },
        ),
    )

    output_path = tmp_path / "dist" / "coworld_manifest.json"
    result = CliRunner().invoke(
        app,
        ["build", str(tmp_path / "compose.yaml"), str(template_path), "0.2.0", str(output_path)],
    )

    assert result.exit_code == 0, result.output
    assert f"Built Coworld manifest: {output_path.resolve()}" in result.output
    built_manifest = json.loads(output_path.read_text(encoding="utf-8"))
    assert built_manifest["game"]["version"] == "0.2.0"
    assert built_manifest["game"]["runnable"]["image"] == "game-runtime:coworld-111111111111"
    assert built_manifest["player"][0]["image"] == "player-runtime:coworld-222222222222"


def test_resolve_and_upload_command_builds_resolved_manifest_then_uploads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    compose_path = tmp_path / "compose.yaml"
    template_path = tmp_path / "coworld_manifest_template.json"
    output_path = tmp_path / "dist" / "coworld_manifest.json"
    compose_path.write_text("services: {}\n", encoding="utf-8")
    template_path.write_text('{"game": {"name": "unit"}}\n', encoding="utf-8")
    build_calls: list[tuple[Path, Path, str, Path, bool]] = []
    upload_calls: list[tuple[Path, str, float]] = []

    def fake_build(
        compose_file: Path,
        template_file: Path,
        version: str,
        manifest_output: Path,
        *,
        resolve_mutable_image_refs: bool = False,
    ) -> Path:
        build_calls.append((compose_file, template_file, version, manifest_output, resolve_mutable_image_refs))
        return manifest_output.resolve()

    def fake_upload(manifest_path: Path, *, server: str, timeout_seconds: float) -> None:
        upload_calls.append((manifest_path, server, timeout_seconds))

    monkeypatch.setattr("coworld.cli.build_coworld_manifest", fake_build)
    monkeypatch.setattr("coworld.cli.upload_coworld_cmd", fake_upload)

    result = CliRunner().invoke(
        app,
        [
            "resolve-and-upload",
            str(compose_path),
            str(template_path),
            "0.2.0",
            str(output_path),
            "--server",
            "http://localhost:3102/api",
            "--timeout-seconds",
            "17",
        ],
    )

    assert result.exit_code == 0, result.output
    assert build_calls == [(compose_path, template_path, "0.2.0", output_path, True)]
    assert upload_calls == [(output_path.resolve(), "http://localhost:3102/api", 17.0)]


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
                # Default stub for bundle image-substitution tests; tests override via role_images.
                "reporter": [
                    {
                        "id": "unit-test-default-reporter",
                        "name": "Unit Test Default Reporter",
                        "type": "reporter",
                        "image": "ghcr.io/metta-ai/reporters-default:latest",
                        "description": "Default reporter stub.",
                    }
                ],
                # Default stub; tests override via role_images.
                "grader": [
                    {
                        "id": "unit-test-default-grader",
                        "name": "Unit Test Default Grader",
                        "type": "grader",
                        "image": "ghcr.io/metta-ai/graders-default:latest",
                        "source_url": "https://github.com/Metta-AI/graders/tree/main/graders/default/default_grader",
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


def _fake_docker_run(
    service_images: Mapping[str, str],
    image_ids: Mapping[str, str],
    calls: list[tuple[list[str], dict[str, object]]] | None = None,
) -> Callable[..., subprocess.CompletedProcess[str]]:
    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if calls is not None:
            calls.append((command, kwargs))
        if command[:3] == ["docker", "compose", "-f"] and command[-3:] == ["config", "--format", "json"]:
            services = {service: {"image": image} for service, image in service_images.items()}
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps({"services": services}))
        if command[:4] == ["docker", "buildx", "imagetools", "inspect"]:
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps({"digest": image_ids[command[4]]}))
        if command[:3] == ["docker", "image", "inspect"]:
            return subprocess.CompletedProcess(command, 0, stdout=f"{image_ids[command[-1]]}\n")
        return subprocess.CompletedProcess(command, 0)

    return fake_run
