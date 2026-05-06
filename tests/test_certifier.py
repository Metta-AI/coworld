from __future__ import annotations

import importlib.util
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
from coworld.episode_runner import (
    REPLAY_LOAD_ENV_VAR,
    REPLAY_SAVE_ENV_VAR,
    EpisodeArtifacts,
    _image_command,
    _replay_client_url,
    assert_docker_image_reachable,
)
from coworld.play import ReplaySession, build_play_links, replay_coworld
from coworld.schema_validation import validate_episode_request


def test_resolve_manifest_uri_relative_to_coworld_manifest(tmp_path: Path) -> None:
    base_dir = tmp_path / "world"
    game_dir = base_dir / "game"
    game_dir.mkdir(parents=True)
    assert (
        resolve_manifest_uri(base_dir, "game/docs/player_protocol_spec.md")
        == (game_dir / "docs" / "player_protocol_spec.md").resolve()
    )


def test_load_coworld_package_validates_inline_game_manifest(tmp_path: Path) -> None:
    coworld_manifest_path = _write_package_files(tmp_path)

    package = load_coworld_package(coworld_manifest_path)

    assert package.manifest_path == coworld_manifest_path.resolve()
    assert package.manifest["game"]["name"] == "unit-test-game"


def test_load_coworld_package_requires_protocol_doc_files(tmp_path: Path) -> None:
    coworld_manifest_path = _write_package_files(tmp_path, write_protocol_docs=False)

    with pytest.raises(FileNotFoundError, match="Cogame protocols.player"):
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


def test_build_game_config_allows_empty_tokens_when_game_schema_does(tmp_path: Path) -> None:
    package = _write_package(tmp_path)

    assert build_game_config(package, [])["tokens"] == []


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
    assert episode_request["players"] == [
        {
            "image": "unit-test-runtime:latest",
            "run": ["python", "-m", "unit_test.player"],
            "env": {"PLAYER_MODE": "test"},
        }
    ]
    assert episode_request["results_uri"] == artifacts.results_path.as_uri()
    assert episode_request["replay_uri"] == artifacts.replay_path.as_uri()
    assert episode_request["logs_uri"] == artifacts.logs_dir.as_uri()


def test_episode_request_allows_no_runner_managed_players() -> None:
    episode_request = {
        "game_config": {"difficulty": "easy"},
        "players": [],
        "results_uri": "file:///tmp/results.json",
    }

    validate_episode_request(episode_request)
    assert build_player_launch_specs(episode_request) == []


def test_build_play_links_point_directly_at_engine_client_routes(tmp_path: Path) -> None:
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

    links = build_play_links(players, ["token-0"], game_port=1234)

    player_link = urlparse(links.players[0])
    assert player_link.scheme == "http"
    assert player_link.netloc == "127.0.0.1:1234"
    assert player_link.path == "/player"
    assert parse_qs(player_link.query) == {
        "slot": ["0"],
        "token": ["token-0"],
        "role": ["x"],
        "difficulty": ["2"],
        "debug": ["True"],
    }

    global_link = urlparse(links.global_)
    assert global_link.scheme == "http"
    assert global_link.netloc == "127.0.0.1:1234"
    assert global_link.path == "/global"
    assert global_link.query == ""

    admin_link = urlparse(links.admin)
    assert admin_link.scheme == "http"
    assert admin_link.netloc == "127.0.0.1:1234"
    assert admin_link.path == "/admin"
    assert admin_link.query == ""


def test_replay_client_url_points_at_engine_replay_route() -> None:
    replay_link = urlparse(_replay_client_url(1234))

    assert REPLAY_SAVE_ENV_VAR == "COGAME_SAVE_REPLAY_PATH"
    assert REPLAY_LOAD_ENV_VAR == "COGAME_LOAD_REPLAY_PATH"
    assert replay_link.scheme == "http"
    assert replay_link.netloc == "127.0.0.1:1234"
    assert replay_link.path == "/replay"
    assert replay_link.query == ""


def test_replay_coworld_starts_replay_container_and_reports_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    coworld_manifest_path = _write_package_files(tmp_path)
    replay_path = tmp_path / "replay.json"
    replay_path.write_text("{}")
    ready_sessions: list[ReplaySession] = []
    popen_commands: list[list[str]] = []

    class FakeProcess:
        def wait(self) -> int:
            return 0

    def fake_popen(cmd, **kwargs):
        popen_commands.append(cmd)
        return FakeProcess()

    monkeypatch.setattr("coworld.play.assert_docker_image_reachable", lambda image, *, label: None)
    monkeypatch.setattr("coworld.play._free_local_port", lambda: 1234)
    monkeypatch.setattr("coworld.play._wait_for_health", lambda port, process, stderr_path, *, timeout_seconds: None)
    monkeypatch.setattr("coworld.play.subprocess.Popen", fake_popen)
    monkeypatch.setattr("coworld.play.subprocess.run", lambda cmd, **kwargs: subprocess.CompletedProcess(cmd, 0))

    session = replay_coworld(
        coworld_manifest_path,
        replay_path,
        workspace=tmp_path / "replay-workspace",
        on_ready=ready_sessions.append,
    )

    assert session.link == "http://127.0.0.1:1234/replay"
    assert ready_sessions == [session]
    command = popen_commands[0]
    assert f"{REPLAY_LOAD_ENV_VAR}=/coworld-replay/replay.json" in command
    assert f"{tmp_path}:/coworld-replay:ro" in command
    assert _image_command_slice(command) == [
        "--entrypoint",
        "python",
        "unit-test-runtime:latest",
        "-m",
        "unit_test.game",
    ]


def test_runnable_run_overrides_docker_entrypoint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    package = _write_package(tmp_path)
    game_command = _image_command(package.cogame)
    player = build_player_launch_specs(build_episode_request(package, EpisodeArtifacts.create(tmp_path / "cert")))[0]
    player_command = _image_command(player)

    assert game_command == ["--entrypoint", "python", "unit-test-runtime:latest", "-m", "unit_test.game"]
    assert player_command == ["--entrypoint", "python", "unit-test-runtime:latest", "-m", "unit_test.player"]


def test_example_coworld_manifest_validates() -> None:
    package = load_coworld_package(_example_root() / "coworld_manifest.json")
    config = build_game_config(package, ["token-0", "token-1"])

    assert package.cogame.image == "coworld-paintarena:latest"
    assert package.cogame.run == ("python", "/app/game/server.py")
    assert package.manifest["game"]["protocols"] == {
        "player": "game/docs/player_protocol_spec.md",
        "global": "game/docs/global_protocol_spec.md",
    }
    assert package.manifest["player"][0]["image"] == "coworld-paintarena:latest"
    assert package.manifest["player"][0]["run"] == ["python", "/app/player/player.py"]
    assert config["tokens"] == ["token-0", "token-1"]


def test_paintarena_snapshots_are_independent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "tokens": ["token-0", "token-1"],
                "width": 12,
                "height": 8,
                "max_ticks": 100,
                "tick_rate": 5,
            }
        )
    )
    monkeypatch.setenv("COGAME_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("COGAME_RESULTS_PATH", str(tmp_path / "results.json"))
    monkeypatch.setenv("COGAME_SAVE_REPLAY_PATH", str(tmp_path / "replay.json"))
    monkeypatch.delenv("COGAME_LOAD_REPLAY_PATH", raising=False)

    spec = importlib.util.spec_from_file_location("paintarena_server_test", _example_root() / "game" / "server.py")
    assert spec is not None
    assert spec.loader is not None
    server_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(server_module)

    first_snapshot = server_module._snapshot()
    server_module._step()
    second_snapshot = server_module._snapshot()
    server_module._step()

    assert first_snapshot["positions"] == [[0, 0], [11, 7]]
    assert first_snapshot["tile_owners"] == [-1 for _ in range(96)]
    assert first_snapshot["scores"] == [0, 0]
    assert second_snapshot["positions"] == [[0, 0], [11, 7]]
    assert second_snapshot["tile_owners"][0] == 0
    assert second_snapshot["tile_owners"][-1] == 1
    assert second_snapshot["scores"] == [1, 1]


def _docker_available() -> bool:
    try:
        subprocess.run(["docker", "info"], capture_output=True, check=True, timeout=10)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return False


@pytest.mark.slow
@pytest.mark.skipif(not _docker_available(), reason="Docker not available")
def test_paintarena_example_certifies_with_docker(tmp_path: Path) -> None:
    example_root = _example_root()
    subprocess.run(
        ["docker", "build", "-t", "coworld-paintarena:latest", "."],
        cwd=example_root,
        check=True,
        timeout=300,
    )

    result = certify_coworld(example_root / "coworld_manifest.json", workspace=tmp_path / "cert", timeout_seconds=60)

    assert sum(result.results["scores"]) > 0
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
    write_protocol_docs: bool = True,
) -> Path:
    world_dir = tmp_path / "world"
    game_dir = world_dir / "game"
    docs_dir = game_dir / "docs"
    docs_dir.mkdir(parents=True)
    if write_protocol_docs:
        (docs_dir / "player_protocol_spec.md").write_text("# Player Protocol\n")
        (docs_dir / "global_protocol_spec.md").write_text("# Global Protocol\n")
    coworld_manifest_path = world_dir / "coworld_manifest.json"
    coworld_manifest_path.write_text(
        json.dumps(
            _coworld_manifest(
                config_schema_required=config_schema_required or ["tokens"],
                certification=certification,
            )
        )
    )
    return coworld_manifest_path


def _coworld_manifest(
    *,
    config_schema_required: list[str] | None = None,
    certification: dict[str, object] | None = None,
) -> dict[str, object]:
    if certification is None:
        certification = {
            "variant_id": "default",
            "players": [{"player_id": "unit-test-player"}],
        }
    return {
        "game": _game_manifest(config_schema_required=config_schema_required or ["tokens"]),
        "player": [
            {
                "id": "unit-test-player",
                "name": "Unit Test Player",
                "type": "player",
                "image": "unit-test-runtime:latest",
                "run": ["python", "-m", "unit_test.player"],
                "env": {"PLAYER_MODE": "test"},
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


def _game_manifest(*, config_schema_required: list[str] | None = None) -> dict[str, object]:
    required = config_schema_required or ["tokens"]
    return {
        "name": "unit-test-game",
        "version": "0.1.0",
        "description": "Unit test Cogame manifest.",
        "owner": "cogames@softmax.com",
        "runnable": {
            "type": "game",
            "image": "unit-test-runtime:latest",
            "run": ["python", "-m", "unit_test.game"],
            "env": {"GAME_MODE": "test"},
        },
        "config_schema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "additionalProperties": False,
            "required": required,
            "properties": {
                "tokens": {
                    "type": "array",
                    "minItems": 0,
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
            "player": "game/docs/player_protocol_spec.md",
            "global": "game/docs/global_protocol_spec.md",
        },
    }


def _example_root() -> Path:
    return Path(__file__).resolve().parents[1] / "examples" / "paintarena"


def _image_command_slice(command: list[str]) -> list[str]:
    entrypoint_index = command.index("--entrypoint")
    return command[entrypoint_index:]
