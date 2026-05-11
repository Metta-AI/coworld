from __future__ import annotations

import importlib.util
import json
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from starlette.websockets import WebSocketDisconnect

from coworld.certifier import (
    build_episode_request,
    build_game_config,
    build_player_launch_specs,
    certify_coworld,
    load_coworld_package,
    load_results,
    resolve_manifest_uri,
)
from coworld.play import ReplaySession, build_play_links, replay_coworld
from coworld.runner.runner import (
    CONFIG_ENV_VAR,
    REPLAY_LOAD_ENV_VAR,
    REPLAY_SAVE_ENV_VAR,
    RESULTS_ENV_VAR,
    EpisodeArtifacts,
    _image_command,
    _replay_client_url,
    assert_docker_image_reachable,
)
from coworld.types import CoworldEpisodeJobSpec, CoworldManifest


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
    assert package.manifest.game.name == "unit-test-game"


def test_load_coworld_package_requires_protocol_doc_files(tmp_path: Path) -> None:
    coworld_manifest_path = _write_package_files(tmp_path, write_protocol_docs=False)

    with pytest.raises(FileNotFoundError, match="Cogame protocols.player"):
        load_coworld_package(coworld_manifest_path)


def test_load_coworld_package_allows_public_protocol_doc_links(tmp_path: Path) -> None:
    coworld_manifest_path = _write_package_files(tmp_path, write_protocol_docs=False)
    manifest = json.loads(coworld_manifest_path.read_text())
    manifest["game"]["protocols"] = {
        "player": "https://example.com/player_protocol_spec.md",
        "global": "https://example.com/global_protocol_spec.md",
    }
    coworld_manifest_path.write_text(json.dumps(manifest))

    package = load_coworld_package(coworld_manifest_path)

    assert package.protocols.player == "https://example.com/player_protocol_spec.md"


def test_load_coworld_package_allows_inlined_protocol_docs(tmp_path: Path) -> None:
    coworld_manifest_path = _write_package_files(tmp_path, write_protocol_docs=False)
    manifest = json.loads(coworld_manifest_path.read_text())
    manifest["game"]["protocols"] = {
        "player": "# Player Protocol\n\nConnect over /player.",
        "global": "# Global Protocol\n\nConnect over /global.",
    }
    coworld_manifest_path.write_text(json.dumps(manifest))

    package = load_coworld_package(coworld_manifest_path)

    assert package.protocols.player.startswith("# Player Protocol")


def test_load_coworld_package_rejects_invalid_certification_player_entry(tmp_path: Path) -> None:
    coworld_manifest_path = _write_package_files(
        tmp_path,
        certification={
            "game_config": {"difficulty": "easy"},
            "players": [{"role": "painter"}],
        },
    )

    with pytest.raises(JsonSchemaValidationError, match="player_id"):
        load_coworld_package(coworld_manifest_path)


def test_load_coworld_package_rejects_extra_certification_player_fields(tmp_path: Path) -> None:
    coworld_manifest_path = _write_package_files(
        tmp_path,
        certification={
            "game_config": {"difficulty": "easy"},
            "players": [{"player_id": "unit-test-player", "role": "painter"}],
        },
    )

    with pytest.raises(JsonSchemaValidationError, match="Additional properties are not allowed"):
        load_coworld_package(coworld_manifest_path)


def test_load_coworld_package_rejects_unknown_certification_player(tmp_path: Path) -> None:
    coworld_manifest_path = _write_package_files(
        tmp_path,
        certification={
            "game_config": {"difficulty": "easy"},
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
    with pytest.raises(JsonSchemaValidationError):
        _write_package(tmp_path, config_schema_required=["tokens", "missing"])


def test_build_game_config_rejects_wrong_token_count(tmp_path: Path) -> None:
    package = _write_package(tmp_path)

    with pytest.raises(JsonSchemaValidationError):
        build_game_config(package, [])


def test_load_coworld_package_requires_fixed_token_count(tmp_path: Path) -> None:
    coworld_manifest_path = _write_package_files(tmp_path)
    manifest = json.loads(coworld_manifest_path.read_text())
    del manifest["game"]["config_schema"]["properties"]["tokens"]["maxItems"]
    coworld_manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(ValueError, match="equal minItems and maxItems"):
        load_coworld_package(coworld_manifest_path)


def test_load_coworld_package_rejects_tokens_in_variant_game_config(tmp_path: Path) -> None:
    coworld_manifest_path = _write_package_files(tmp_path)
    manifest = json.loads(coworld_manifest_path.read_text())
    manifest["variants"][0]["game_config"]["tokens"] = ["token-0"]
    coworld_manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(ValueError, match="must not include runner-managed tokens"):
        load_coworld_package(coworld_manifest_path)


def test_load_coworld_package_requires_certification_player_count_to_match_tokens(tmp_path: Path) -> None:
    coworld_manifest_path = _write_package_files(
        tmp_path,
        certification={
            "game_config": {"difficulty": "easy"},
            "players": [{"player_id": "unit-test-player"}, {"player_id": "unit-test-player"}],
        },
    )

    with pytest.raises(ValueError, match="certification.players must match"):
        load_coworld_package(coworld_manifest_path)


def test_load_results_validates_against_cogame_results_schema(tmp_path: Path) -> None:
    package = _write_package(tmp_path)
    artifacts = EpisodeArtifacts.create(tmp_path / "cert")
    artifacts.results_path.write_text(json.dumps({"winner": 0}))

    with pytest.raises(JsonSchemaValidationError, match="'scores' is a required property"):
        load_results(package, artifacts)


def test_build_episode_request_matches_runner_spec_shape(tmp_path: Path) -> None:
    package = _write_package(tmp_path)
    artifacts = EpisodeArtifacts.create(tmp_path / "cert")

    episode_request = build_episode_request(package, artifacts)

    assert CoworldManifest.model_validate(episode_request["manifest"]) == package.manifest
    assert episode_request["game_config"] == {"difficulty": "easy"}
    assert episode_request["players"] == [
        {
            "image": "unit-test-runtime:latest",
            "run": ["python", "-m", "unit_test.player"],
            "env": {"PLAYER_MODE": "test"},
        }
    ]
    assert "results_uri" not in episode_request
    assert "replay_uri" not in episode_request
    assert "logs_uri" not in episode_request


def test_episode_request_allows_no_runner_managed_players() -> None:
    episode_request = {
        "manifest": _coworld_manifest(),
        "game_config": {"difficulty": "easy", "players": []},
        "players": [],
    }

    CoworldEpisodeJobSpec.model_validate(episode_request)
    assert build_player_launch_specs(episode_request) == []


def test_build_play_links_point_directly_at_engine_client_routes(tmp_path: Path) -> None:
    package = _write_package(
        tmp_path,
        game_config={"difficulty": "easy", "players": [{"role": "x", "difficulty": 2, "debug": True}]},
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
    }
    game_config = cast(dict[str, object], episode_request["game_config"])
    assert game_config["players"] == [{"role": "x", "difficulty": 2, "debug": True}]

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

    assert REPLAY_SAVE_ENV_VAR == "COGAME_SAVE_REPLAY_URI"
    assert REPLAY_LOAD_ENV_VAR == "COGAME_LOAD_REPLAY_URI"
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

    def noop_assert_docker_image_reachable(image: str, *, label: str) -> None:
        pass

    def noop_wait_for_health(
        port: int, process: subprocess.Popen, stderr_path: Path, *, timeout_seconds: float
    ) -> None:
        pass

    monkeypatch.setattr("coworld.play.assert_docker_image_reachable", noop_assert_docker_image_reachable)
    monkeypatch.setattr("coworld.play._free_local_port", lambda: 1234)
    monkeypatch.setattr("coworld.play._wait_for_health", noop_wait_for_health)
    monkeypatch.setattr("coworld.play.subprocess.Popen", fake_popen)
    monkeypatch.setattr(
        "coworld.play.subprocess.run",
        lambda cmd, **kwargs: subprocess.CompletedProcess(cmd, 0),
    )

    session = replay_coworld(
        coworld_manifest_path,
        replay_path,
        workspace=tmp_path / "replay-workspace",
        on_ready=ready_sessions.append,
    )

    assert session.link == "http://127.0.0.1:1234/replay"
    assert ready_sessions == [session]
    command = popen_commands[0]
    assert f"{REPLAY_LOAD_ENV_VAR}=file:///coworld-replay/replay.json" in command
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
    assert package.manifest.game.protocols.player == "game/docs/player_protocol_spec.md"
    assert package.manifest.game.protocols.global_ == "game/docs/global_protocol_spec.md"
    assert package.manifest.player[0].image == "coworld-paintarena:latest"
    assert package.manifest.player[0].run == ["python", "/app/player/player.py"]
    assert config["tokens"] == ["token-0", "token-1"]


def test_paintarena_snapshots_are_independent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "tokens": ["token-0", "token-1"],
                "players": [{"name": "Sweep Painter 1"}, {"name": "Sweep Painter 2"}],
                "width": 12,
                "height": 8,
                "max_ticks": 100,
                "tick_rate": 5,
            }
        )
    )
    monkeypatch.setenv(CONFIG_ENV_VAR, config_path.as_uri())
    monkeypatch.setenv(RESULTS_ENV_VAR, (tmp_path / "results.json").as_uri())
    monkeypatch.setenv(REPLAY_SAVE_ENV_VAR, (tmp_path / "replay.json").as_uri())
    monkeypatch.delenv(REPLAY_LOAD_ENV_VAR, raising=False)

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
    assert first_snapshot["player_names"] == ["Sweep Painter 1", "Sweep Painter 2"]
    assert server_module._replay_payload({"scores": [0.0, 0.0]})["player_names"] == [
        "Sweep Painter 1",
        "Sweep Painter 2",
    ]
    assert second_snapshot["positions"] == [[0, 0], [11, 7]]
    assert second_snapshot["tile_owners"][0] == 0
    assert second_snapshot["tile_owners"][-1] == 1
    assert second_snapshot["scores"] == [1, 1]


def test_paintarena_starts_after_player_connect_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "config.json"
    results_path = tmp_path / "results.json"
    replay_path = tmp_path / "replay.json"
    config_path.write_text(
        json.dumps(
            {
                "tokens": ["token-0", "token-1"],
                "players": [{"name": "Sweep Painter 1"}, {"name": "Sweep Painter 2"}],
                "width": 12,
                "height": 8,
                "max_ticks": 1,
                "tick_rate": 100,
                "player_connect_timeout_seconds": 0.01,
            }
        )
    )
    monkeypatch.setenv(CONFIG_ENV_VAR, config_path.as_uri())
    monkeypatch.setenv(RESULTS_ENV_VAR, results_path.as_uri())
    monkeypatch.setenv(REPLAY_SAVE_ENV_VAR, replay_path.as_uri())
    monkeypatch.delenv(REPLAY_LOAD_ENV_VAR, raising=False)

    spec = importlib.util.spec_from_file_location("paintarena_timeout_test", _example_root() / "game" / "server.py")
    assert spec is not None
    assert spec.loader is not None
    server_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(server_module)
    server_module_typed = cast(Any, server_module)
    server_module_typed.server = SimpleNamespace(should_exit=False)

    with TestClient(server_module_typed.app):
        deadline = time.monotonic() + 1
        while not results_path.exists() and time.monotonic() < deadline:
            time.sleep(0.01)

    assert json.loads(results_path.read_text()) == {"scores": [1.0, 1.0], "painted_tiles": [1, 1], "ticks": 1}
    assert json.loads(replay_path.read_text())["frames"][0]["started"] is True


def test_paintarena_disconnected_player_noops_after_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "config.json"
    results_path = tmp_path / "results.json"
    replay_path = tmp_path / "replay.json"
    config_path.write_text(
        json.dumps(
            {
                "tokens": ["token-0", "token-1"],
                "players": [{"name": "Sweep Painter 1"}, {"name": "Sweep Painter 2"}],
                "width": 12,
                "height": 8,
                "max_ticks": 1,
                "tick_rate": 100,
                "player_connect_timeout_seconds": 0.05,
            }
        )
    )
    monkeypatch.setenv(CONFIG_ENV_VAR, config_path.as_uri())
    monkeypatch.setenv(RESULTS_ENV_VAR, results_path.as_uri())
    monkeypatch.setenv(REPLAY_SAVE_ENV_VAR, replay_path.as_uri())
    monkeypatch.delenv(REPLAY_LOAD_ENV_VAR, raising=False)

    spec = importlib.util.spec_from_file_location("paintarena_disconnect_test", _example_root() / "game" / "server.py")
    assert spec is not None
    assert spec.loader is not None
    server_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(server_module)
    server_module_typed = cast(Any, server_module)
    server_module_typed.server = SimpleNamespace(should_exit=False)

    with TestClient(server_module_typed.app) as client:
        with client.websocket_connect("/player?slot=0&token=token-0") as websocket:
            assert websocket.receive_json()["slot"] == 0
        deadline = time.monotonic() + 1
        while not results_path.exists() and time.monotonic() < deadline:
            time.sleep(0.01)

    assert json.loads(results_path.read_text()) == {"scores": [1.0, 1.0], "painted_tiles": [1, 1], "ticks": 1}
    assert json.loads(replay_path.read_text())["frames"][0]["started"] is True


def test_cogs_vs_clips_coworld_manifest_validates() -> None:
    package = load_coworld_package(_cogs_vs_clips_root() / "coworld_manifest.json")
    tokens = [f"token-{index}" for index in range(8)]
    config = build_game_config(package, tokens)

    assert package.manifest.game.name == "cogs_vs_clips"
    assert package.cogame.image == "coworld-cogs-vs-clips-game:latest"
    assert package.cogame.run == ("python", "/app/server.py")
    assert package.manifest.game.protocols.player == "game/docs/player_protocol_spec.md"
    assert package.manifest.game.protocols.global_ == "game/docs/global_protocol_spec.md"
    assert package.manifest.player[0].id == "starter-policy-player"
    assert package.manifest.player[0].image == "coworld-mettagrid-policy-player:latest"
    assert package.manifest.player[0].run == ["python", "/app/coworld_policy_player.py"]
    assert package.manifest.player[0].env == {
        "COGAMES_POLICY_URI": "metta://policy/cogames.policy.starter_agent.StarterPolicy"
    }
    daily_variant = next(variant for variant in package.manifest.variants if variant.id == "machina-1-daily")
    assert daily_variant.game_config["max_steps"] == 10000
    assert config == {
        "mission": "cogsguard",
        "max_steps": 3,
        "seed": 0,
        "step_seconds": 0.02,
        "tokens": tokens,
    }


def test_cogs_vs_clips_player_websocket_rejects_missing_query_params(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server_module = _load_cogs_vs_clips_server_module()

    class FakeGame:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self.tokens = ["token-0"]

    monkeypatch.setattr(server_module, "CogsVsClipsGame", FakeGame)
    app = server_module.create_app(
        {
            "mission": "cogsguard",
            "tokens": ["token-0"],
            "max_steps": 3,
            "seed": 0,
            "step_seconds": 0.02,
        },
        results_path=tmp_path / "results.json",
        replay_path=None,
    )

    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/player"):
            pass

    assert exc_info.value.code == 1008


def test_cogs_vs_clips_global_baseline_includes_walls_and_agents(tmp_path: Path) -> None:
    server_module = _load_cogs_vs_clips_server_module()
    game = server_module.CogsVsClipsGame(
        {
            "mission": "machina_1",
            "tokens": ["token-0", "token-1"],
            "max_steps": 3,
            "seed": 0,
            "step_seconds": 0.02,
        },
        results_path=tmp_path / "results.json",
        replay_path=None,
        request_shutdown=lambda: None,
    )

    message = game.global_baseline_message()

    assert message["type"] == "step"
    type_names = {obj["type_name"] for obj in message["objects"]}
    assert "wall" in type_names
    agent_ids = {obj["agent_id"] for obj in message["objects"] if obj.get("is_agent")}
    assert agent_ids == {0, 1}
    assert not hasattr(game, "walls_message")


def test_cogs_vs_clips_global_delta_omits_walls(tmp_path: Path) -> None:
    server_module = _load_cogs_vs_clips_server_module()
    game = server_module.CogsVsClipsGame(
        {
            "mission": "machina_1",
            "tokens": ["token-0", "token-1"],
            "max_steps": 3,
            "seed": 0,
            "step_seconds": 0.02,
        },
        results_path=tmp_path / "results.json",
        replay_path=None,
        request_shutdown=lambda: None,
    )

    message = game.global_delta_message()

    assert message["type"] == "step"
    type_names = {obj["type_name"] for obj in message["objects"]}
    assert "wall" not in type_names
    agent_ids = {obj["agent_id"] for obj in message["objects"] if obj.get("is_agent")}
    assert agent_ids == {0, 1}


def _docker_available() -> bool:
    try:
        subprocess.run(["docker", "info"], capture_output=True, check=True, timeout=10)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return False


@pytest.mark.slow
@pytest.mark.skip(reason="Docker certifier integration is too slow for CI")
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

    scores = cast(list[int], result.results["scores"])
    assert sum(scores) > 0
    assert result.artifacts.replay_path.exists()
    assert result.artifacts.game_stdout_path.exists()
    assert result.artifacts.game_stderr_path.exists()


def _write_package(
    tmp_path: Path,
    *,
    config_schema_required: list[str] | None = None,
    certification: dict[str, object] | None = None,
    game_config: dict[str, object] | None = None,
):
    return load_coworld_package(
        _write_package_files(
            tmp_path,
            config_schema_required=config_schema_required or ["tokens"],
            certification=certification,
            game_config=game_config,
        )
    )


def _write_package_files(
    tmp_path: Path,
    *,
    config_schema_required: list[str] | None = None,
    certification: dict[str, object] | None = None,
    game_config: dict[str, object] | None = None,
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
                game_config=game_config,
            )
        )
    )
    return coworld_manifest_path


def _coworld_manifest(
    *,
    config_schema_required: list[str] | None = None,
    certification: dict[str, object] | None = None,
    game_config: dict[str, object] | None = None,
) -> dict[str, object]:
    if certification is None:
        certification = {
            "game_config": game_config or {"difficulty": "easy"},
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
                "game_config": game_config or {"difficulty": "easy"},
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
                    "minItems": 1,
                    "maxItems": 1,
                    "items": {"type": "string", "minLength": 1},
                },
                "difficulty": {"type": "string"},
                "players": {"type": "array", "items": {"type": "object"}},
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
    return Path(__file__).resolve().parents[1] / "src" / "coworld" / "examples" / "paintarena"


def _image_command_slice(command: list[str]) -> list[str]:
    entrypoint_index = command.index("--entrypoint")
    return command[entrypoint_index:]


def _cogs_vs_clips_root() -> Path:
    return Path(__file__).resolve().parents[1] / "src" / "coworld" / "examples" / "cogs_vs_clips"


def _load_cogs_vs_clips_server_module():
    spec = importlib.util.spec_from_file_location(
        "cogs_vs_clips_server_test",
        _cogs_vs_clips_root() / "game" / "server.py",
    )
    assert spec is not None
    assert spec.loader is not None
    server_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(server_module)
    return server_module
