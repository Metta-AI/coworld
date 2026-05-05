from __future__ import annotations

import json
import subprocess
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from jsonschema.exceptions import ValidationError

from coworld.certifier import (
    build_episode_request,
    build_game_config,
    build_player_launch_specs,
    certify_coworld,
    load_coworld_package,
    load_results,
    resolve_manifest_uri,
)
from coworld.episode_runner import EpisodeArtifacts, assert_docker_image_reachable
from coworld.play import build_play_links


def test_resolve_manifest_uri_relative_to_coworld_manifest(tmp_path: Path) -> None:
    base_dir = tmp_path / "world"
    game_dir = base_dir / "game"
    game_dir.mkdir(parents=True)
    assert resolve_manifest_uri(base_dir, "game/cogame_manifest.json") == (game_dir / "cogame_manifest.json").resolve()


def test_load_coworld_package_validates_and_resolves_game_manifest(tmp_path: Path) -> None:
    coworld_manifest_path = _write_package_files(tmp_path)
    cogame_manifest_path = coworld_manifest_path.parent / "game" / "cogame_manifest.json"

    package = load_coworld_package(coworld_manifest_path)

    assert package.manifest_path == coworld_manifest_path.resolve()
    assert package.cogame_manifest_path == cogame_manifest_path.resolve()
    assert package.cogame_manifest["name"] == "unit-test-game"


def test_load_coworld_package_requires_protocol_doc_files(tmp_path: Path) -> None:
    coworld_manifest_path = _write_package_files(tmp_path, write_protocol_docs=False)

    with pytest.raises(FileNotFoundError, match="Cogame protocols.player"):
        load_coworld_package(coworld_manifest_path)


def test_load_coworld_package_requires_client_files(tmp_path: Path) -> None:
    coworld_manifest_path = _write_package_files(tmp_path, write_clients=False)

    with pytest.raises(FileNotFoundError, match="Coworld clients.player"):
        load_coworld_package(coworld_manifest_path)


def test_load_coworld_package_rejects_invalid_certification_player_entry(tmp_path: Path) -> None:
    coworld_manifest_path = _write_package_files(
        tmp_path,
        certification={
            "variant_id": "default",
            "players": [{"initial_params": {"difficulty": "easy"}}],
        },
    )

    with pytest.raises(ValidationError, match="'player_id' is a required property"):
        load_coworld_package(coworld_manifest_path)


def test_load_coworld_package_rejects_invalid_initial_params(tmp_path: Path) -> None:
    coworld_manifest_path = _write_package_files(
        tmp_path,
        certification={
            "variant_id": "default",
            "players": [{"player_id": "unit-test-player", "initial_params": {"bad": ["nested"]}}],
        },
    )

    with pytest.raises(ValidationError, match="is not of type"):
        load_coworld_package(coworld_manifest_path)


def test_load_coworld_package_rejects_unknown_certification_variant(tmp_path: Path) -> None:
    coworld_manifest_path = _write_package_files(
        tmp_path,
        certification={
            "variant_id": "missing",
            "players": [{"player_id": "unit-test-player"}],
        },
    )

    with pytest.raises(ValueError, match="unknown certification variant_id"):
        load_coworld_package(coworld_manifest_path)


def test_load_coworld_package_rejects_unknown_certification_player(tmp_path: Path) -> None:
    coworld_manifest_path = _write_package_files(
        tmp_path,
        certification={
            "variant_id": "default",
            "players": [{"player_id": "missing"}],
        },
    )

    with pytest.raises(ValueError, match="unknown certification player_id"):
        load_coworld_package(coworld_manifest_path)


def test_assert_docker_image_reachable_accepts_local_image(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="[]", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert_docker_image_reachable("local-image:latest")

    assert calls == [["docker", "image", "inspect", "local-image:latest"]]


def test_assert_docker_image_reachable_accepts_remote_image(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 1 if cmd[1:3] == ["image", "inspect"] else 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert_docker_image_reachable("ghcr.io/example/image:latest")

    assert calls == [
        ["docker", "image", "inspect", "ghcr.io/example/image:latest"],
        ["docker", "manifest", "inspect", "ghcr.io/example/image:latest"],
    ]


def test_assert_docker_image_reachable_rejects_missing_image(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="missing image")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="Missing image"):
        assert_docker_image_reachable("missing:latest", label="Missing image")


def test_build_game_config_validates_after_tokens_are_injected_via_json_schema(tmp_path: Path) -> None:
    package = _write_package(tmp_path, config_schema_required=["tokens", "missing"])

    with pytest.raises(ValidationError):
        build_game_config(package, ["token-0"])


def test_load_results_validates_against_cogame_results_schema(tmp_path: Path) -> None:
    package = _write_package(tmp_path)
    artifacts = EpisodeArtifacts.create(tmp_path / "cert")
    artifacts.results_path.write_text(json.dumps({"winner": 0}))

    with pytest.raises(ValidationError, match="'scores' is a required property"):
        load_results(package, artifacts)


def test_build_episode_request_adds_artifact_destinations(tmp_path: Path) -> None:
    package = _write_package(tmp_path)
    artifacts = EpisodeArtifacts.create(tmp_path / "cert")

    episode_request = build_episode_request(package, artifacts)

    assert episode_request["game_config"] == {"difficulty": "easy"}
    assert episode_request["players"] == [{"image": "unit-test-player:latest"}]
    assert episode_request["results_uri"] == artifacts.results_path.as_uri()
    assert episode_request["replay_uri"] == artifacts.replay_path.as_uri()
    assert episode_request["logs_uri"] == artifacts.logs_dir.as_uri()


def test_build_play_links_pass_complete_address_to_clients(tmp_path: Path) -> None:
    package = _write_package(
        tmp_path,
        certification={
            "variant_id": "default",
            "players": [
                {
                    "player_id": "unit-test-player",
                    "initial_params": {"role": "x", "difficulty": 2, "debug": True},
                }
            ],
        },
    )
    artifacts = EpisodeArtifacts.create(tmp_path / "cert")
    episode_request = build_episode_request(package, artifacts)
    players = build_player_launch_specs(episode_request)

    links = build_play_links(package, players, ["token-0"], game_port=1234, client_port=5678)

    player_link = urlparse(links.players[0])
    player_link_query = parse_qs(player_link.query)
    player_address = urlparse(player_link_query["address"][0])
    player_address_query = parse_qs(player_address.query)
    assert player_link.path == "/clients/player.html"
    assert player_address.geturl().startswith("ws://127.0.0.1:1234/player?")
    assert player_address_query == {
        "slot": ["0"],
        "token": ["token-0"],
        "role": ["x"],
        "difficulty": ["2"],
        "debug": ["True"],
    }

    global_link = urlparse(links.global_)
    global_address = parse_qs(global_link.query)["address"][0]
    assert global_link.path == "/clients/global.html"
    assert global_address == "ws://127.0.0.1:1234/global"


def test_example_coworld_manifest_validates() -> None:
    package = load_coworld_package(_example_root() / "coworld_manifest.json")
    config = build_game_config(package, ["token-0", "token-1"])

    assert package.cogame_manifest["image_uri"] == "coworld-tictactoe-game:latest"
    assert package.cogame_manifest["protocols"] == {
        "player": "docs/player_protocol_spec.md",
        "global": "docs/global_protocol_spec.md",
    }
    assert config["tokens"] == ["token-0", "token-1"]


def _docker_available() -> bool:
    try:
        subprocess.run(["docker", "info"], capture_output=True, check=True, timeout=10)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return False


@pytest.mark.slow
@pytest.mark.skipif(not _docker_available(), reason="Docker not available")
def test_tictactoe_example_certifies_with_docker(tmp_path: Path) -> None:
    example_root = _example_root()
    subprocess.run(
        ["docker", "build", "-t", "coworld-tictactoe-game:latest", "game"],
        cwd=example_root,
        check=True,
        timeout=300,
    )
    subprocess.run(
        ["docker", "build", "-t", "coworld-tictactoe-player:latest", "player"],
        cwd=example_root,
        check=True,
        timeout=300,
    )

    result = certify_coworld(example_root / "coworld_manifest.json", workspace=tmp_path / "cert", timeout_seconds=60)

    assert result.results["scores"] == [1.0, 0.0]
    assert result.artifacts.replay_path.exists()
    assert result.artifacts.game_stdout_path.exists()
    assert result.artifacts.game_stderr_path.exists()


def _write_package(
    tmp_path: Path,
    *,
    config_schema_required: list[str] | None = None,
    certification: dict[str, object] | None = None,
):
    return load_coworld_package(
        _write_package_files(
            tmp_path,
            config_schema_required=config_schema_required or ["tokens"],
            certification=certification,
        )
    )


def _write_package_files(
    tmp_path: Path,
    *,
    config_schema_required: list[str] | None = None,
    certification: dict[str, object] | None = None,
    write_clients: bool = True,
    write_protocol_docs: bool = True,
) -> Path:
    world_dir = tmp_path / "world"
    game_dir = world_dir / "game"
    clients_dir = world_dir / "clients"
    docs_dir = game_dir / "docs"
    docs_dir.mkdir(parents=True)
    clients_dir.mkdir(parents=True)
    (game_dir / "cogame_manifest.json").write_text(
        json.dumps(_cogame_manifest(config_schema_required=config_schema_required or ["tokens"]))
    )
    if write_clients:
        (clients_dir / "player.html").write_text("<!doctype html>")
        (clients_dir / "global.html").write_text("<!doctype html>")
    if write_protocol_docs:
        (docs_dir / "player_protocol_spec.md").write_text("# Player Protocol\n")
        (docs_dir / "global_protocol_spec.md").write_text("# Global Protocol\n")
    coworld_manifest_path = world_dir / "coworld_manifest.json"
    coworld_manifest_path.write_text(json.dumps(_coworld_manifest(certification=certification)))
    return coworld_manifest_path


def _coworld_manifest(*, certification: dict[str, object] | None = None) -> dict[str, object]:
    if certification is None:
        certification = {
            "variant_id": "default",
            "players": [{"player_id": "unit-test-player"}],
        }
    return {
        "game": {"manifest_uri": "game/cogame_manifest.json"},
        "clients": {
            "player": "clients/player.html",
            "global": "clients/global.html",
        },
        "player": [
            {
                "id": "unit-test-player",
                "name": "Unit Test Player",
                "image_uri": "unit-test-player:latest",
                "description": "Unit test player.",
            }
        ],
        "variants": [
            {
                "id": "default",
                "name": "Default",
                "game_config": {"difficulty": "easy"},
                "description": "Default test variant.",
            }
        ],
        "certification": certification,
    }


def _cogame_manifest(*, config_schema_required: list[str] | None = None) -> dict[str, object]:
    required = config_schema_required or ["tokens"]
    return {
        "name": "unit-test-game",
        "version": "0.1.0",
        "description": "Unit test Cogame manifest.",
        "owner": "cogames@softmax.com",
        "image_uri": "unit-test-game:latest",
        "config_schema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "additionalProperties": False,
            "required": required,
            "properties": {
                "tokens": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"type": "string", "minLength": 1},
                },
                "difficulty": {"type": "string"},
            },
        },
        "results_schema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "required": ["scores"],
            "properties": {"scores": {"type": "array", "items": {"type": "number"}}},
        },
        "protocols": {
            "player": "docs/player_protocol_spec.md",
            "global": "docs/global_protocol_spec.md",
        },
    }


def _example_root() -> Path:
    return Path(__file__).resolve().parents[1] / "examples" / "tictactoe"
