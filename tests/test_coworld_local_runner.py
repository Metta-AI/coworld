import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from coworld.runner import runner as runner_module
from coworld.runner.runner import EpisodeArtifacts
from coworld.types import CoworldEpisodeJobSpec, CoworldPlayerFileSpec, CoworldRunnableSpec


def _game_hosted_job(contents: list[bytes]) -> CoworldEpisodeJobSpec:
    players = []
    for content in contents:
        content_hash = hashlib.sha256(content).hexdigest()
        players.append(
            CoworldPlayerFileSpec(
                type="player-file",
                content_hash=content_hash,
                size_bytes=len(content),
            )
        )
    return cast(
        CoworldEpisodeJobSpec,
        SimpleNamespace(
            manifest=SimpleNamespace(
                game=SimpleNamespace(
                    player_runtime="game-hosted",
                    task_environments={},
                    replay_viewer=None,
                    version="1.0",
                    name="test-game",
                    runnable=CoworldRunnableSpec(type="game", image="game:latest"),
                )
            ),
            game_runnable=CoworldRunnableSpec(type="game", image="game:latest"),
            players=players,
            game_config={},
            config_schema={},
            results_schema={},
        ),
    )


def test_game_hosted_local_runner_rejects_mismatched_source_before_start(monkeypatch, tmp_path: Path) -> None:
    job = _game_hosted_job([b"expected"])
    source = tmp_path / "source"
    source.write_bytes(b"different")
    monkeypatch.setattr(runner_module, "assert_episode_images_reachable", lambda _job: None)
    monkeypatch.setattr(
        runner_module,
        "run_game_hosted_container",
        lambda *_args, **_kwargs: pytest.fail("mismatched player file started the game"),
    )

    with pytest.raises(runner_module.RunnerEpisodeError) as exc_info:
        runner_module.run_coworld_episode(
            job,
            EpisodeArtifacts.create(tmp_path / "work"),
            timeout_seconds=30,
            player_file_paths=[source],
        )

    assert exc_info.value.error_type == "player_file_mismatch"


def test_local_resource_admission_preserves_declared_limits_and_bounds_replay(monkeypatch, tmp_path: Path) -> None:
    game = runner_module.CoworldRunnableSpec.model_validate(
        {
            "type": "game",
            "image": "game:latest",
            "resources": {"requests": {"cpu": "2", "memory": "2Gi"}, "limits": {"cpu": "750m"}},
        }
    )
    artifacts = EpisodeArtifacts.create(tmp_path / "work")
    artifacts.replay_path.write_text("{}")
    launch = runner_module.RunnableLaunchSpec.from_model(game)
    command = runner_module.game_container_command(
        launch,
        artifacts,
        container_name="owned-game",
        network_alias="owned-alias",
        local_ports=[],
        include_player_seats=True,
    )
    commands = [command]

    def stop_before_launch(command, **kwargs):
        commands.append(command)
        raise RuntimeError("test stops before Docker allocation")

    network = runner_module.LocalEpisodeNetwork("bridge", None, "test", creation_seconds=30)
    monkeypatch.setattr(network, "create", stop_before_launch)
    monkeypatch.setattr(runner_module.subprocess, "run", lambda *args, **kwargs: None)
    with pytest.raises(RuntimeError, match="before Docker allocation"):
        runner_module.verify_replay_loadable(
            launch,
            artifacts,
            network=network,
            timeout_seconds=30,
        )
    assert len(commands) == 2
    for command in commands:
        assert float(command[command.index("--cpus") + 1]) == 0.75
        assert int(command[command.index("--memory") + 1]) == 2 * 1024**3
        assert command[command.index("--memory-swap") + 1] == command[command.index("--memory") + 1]


def test_local_player_create_uses_its_declared_resource_profile(monkeypatch, tmp_path: Path) -> None:
    runnable = CoworldRunnableSpec.model_validate(
        {
            "type": "player",
            "image": "player:latest",
            "resources": {"requests": {"cpu": "100m", "memory": "128Mi"}},
        }
    )
    player = runner_module.PlayerLaunchSpec.from_model(runnable)
    spec = runner_module.EpisodeRunSpec(
        game=runner_module.RunnableLaunchSpec(image="game:latest"),
        players=[player],
        tokens=["test-token"],
        artifacts=EpisodeArtifacts.create(tmp_path / "work"),
        timeout_seconds=30,
    )
    commands: list[list[str]] = []

    def stop_at_player_create(command, **kwargs):
        if command[:2] == ["docker", "create"]:
            commands.append(command)
            raise RuntimeError("test stops before player allocation")

    async def reject_bad_player(*args, **kwargs):
        return None

    monkeypatch.setattr(runner_module, "ensure_local_docker_network", lambda: None)
    monkeypatch.setattr(runner_module, "_wait_for_published_port", lambda *args, **kwargs: 12345)
    monkeypatch.setattr(runner_module, "_wait_for_health", lambda *args, **kwargs: None)
    monkeypatch.setattr(runner_module, "_require_http_ok", lambda *args, **kwargs: None)
    monkeypatch.setattr(runner_module, "_require_bad_player_rejected", reject_bad_player)
    monkeypatch.setattr(runner_module.subprocess, "Popen", lambda *args, **kwargs: object())
    monkeypatch.setattr(runner_module.subprocess, "run", stop_at_player_create)
    with pytest.raises(RuntimeError, match="before player allocation"):
        runner_module.run_episode_containers(spec, verify_replay=False)
    assert len(commands) == 1
    command = commands[0]
    assert command[command.index("--cpus") + 1] == "0.1"
    assert command[command.index("--memory") + 1] == str(128 * 1024**2)
    assert command[command.index("--memory-swap") + 1] == str(128 * 1024**2)


def test_local_secret_resolution_preserves_manifest_and_requires_explicit_mapping(monkeypatch) -> None:
    secret = "secret://coworld/example/worker-key"
    env = {"WORKER_KEY_URI": secret, "OTHER": "unchanged"}
    monkeypatch.delenv(runner_module.LOCAL_SECRET_URIS_ENV_VAR, raising=False)
    with pytest.raises(ValueError, match="needs a URI in COWORLD_LOCAL_SECRET_URIS"):
        runner_module.local_game_env(env, [])
    monkeypatch.setenv(
        runner_module.LOCAL_SECRET_URIS_ENV_VAR,
        json.dumps({secret: "http://local-secret-service/key", "OTHER": "file:///unrelated"}),
    )
    resolved = runner_module.local_game_env(env, [])
    assert resolved["WORKER_KEY_URI"] == "http://local-secret-service/key"
    assert resolved["OTHER"] == "unchanged"
    assert env == {"WORKER_KEY_URI": secret, "OTHER": "unchanged"}
    monkeypatch.setenv(runner_module.LOCAL_SECRET_URIS_ENV_VAR, json.dumps({secret: secret}))
    with pytest.raises(ValueError, match="String should match pattern"):
        runner_module.local_game_env(env, [])
