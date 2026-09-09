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
            manifest=SimpleNamespace(game=SimpleNamespace(player_runtime="game-hosted")),
            game_runnable=CoworldRunnableSpec(type="game", image="game:latest"),
            players=players,
            game_config={},
            config_schema={},
            results_schema={},
        ),
    )


def test_episode_artifacts_resolve_relative_workspace(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)

    artifacts = EpisodeArtifacts.create(Path("episode"))

    assert artifacts.workspace == tmp_path / "episode"
    assert artifacts.config_path == tmp_path / "episode" / "config.json"
    assert artifacts.policy_artifact_path(0) == tmp_path / "episode" / "policy_artifact_0.zip"


def test_local_game_container_commands_differ_only_by_player_seats_uri(tmp_path: Path) -> None:
    game = runner_module.RunnableLaunchSpec(image="game:latest", env={"GAME_SETTING": "value"})
    artifacts = EpisodeArtifacts.create(tmp_path / "work")
    common = {
        "container_name": "coworld-game",
        "network_alias": "coworld-game-local",
        "port": 12345,
        "local_ports": [],
    }

    platform_command = runner_module.game_container_command(
        game,
        artifacts,
        **common,
        include_player_seats=False,
    )
    game_hosted_command = runner_module.game_container_command(
        game,
        artifacts,
        **common,
        include_player_seats=True,
    )

    seats_env = "COGAME_PLAYER_SEATS_URI=file:///coworld/player_seats.json"
    seats_index = game_hosted_command.index(seats_env)
    assert game_hosted_command[seats_index - 1] == "-e"
    assert game_hosted_command[: seats_index - 1] + game_hosted_command[seats_index + 1 :] == platform_command


def test_game_hosted_local_runner_stages_files_and_starts_only_game(monkeypatch, tmp_path: Path) -> None:
    contents = [b"first player", b"second player"]
    sources = []
    for slot, content in enumerate(contents):
        source = tmp_path / f"source-{slot}"
        source.write_bytes(content)
        sources.append(source)
    job = _game_hosted_job(contents)
    artifacts = EpisodeArtifacts.create(tmp_path / "work")
    docker_commands: list[list[str]] = []

    global_message_kwargs: list[dict[str, object]] = []

    async def global_message(*_args, **kwargs):
        global_message_kwargs.append(kwargs)
        return None

    def popen(command, **_kwargs):
        docker_commands.append(command)
        return object()

    monkeypatch.setattr(runner_module, "assert_episode_images_reachable", lambda _job: None)
    monkeypatch.setattr(runner_module, "ensure_local_docker_network", lambda: None)
    monkeypatch.setattr(runner_module, "_free_local_port", lambda: 12345)
    monkeypatch.setattr(runner_module, "_wait_for_health", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(runner_module, "_require_http_ok", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(runner_module, "_require_global_message", global_message)
    monkeypatch.setattr(
        runner_module,
        "_wait_for_game_results_or_exit",
        lambda *_args, **_kwargs: artifacts.results_path.write_text("{}", encoding="utf-8"),
    )
    monkeypatch.setattr(runner_module.subprocess, "Popen", popen)
    monkeypatch.setattr(
        runner_module.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0),
    )
    monkeypatch.setattr(
        runner_module,
        "run_episode_containers",
        lambda *_args, **_kwargs: pytest.fail("game-hosted execution started player containers"),
    )

    runner_module.run_coworld_episode(
        job,
        artifacts,
        timeout_seconds=30,
        player_file_paths=sources,
        require_websocket_pong=True,
    )

    assert len(docker_commands) == 1
    # Certification's pong requirement reaches the game-hosted lifecycle too.
    assert global_message_kwargs[0]["require_pong"] is True
    assert "COGAME_PLAYER_SEATS_URI=file:///coworld/player_seats.json" in docker_commands[0]
    assert [artifacts.player_file_path(slot).read_bytes() for slot in range(2)] == contents
    seats = json.loads(artifacts.player_seats_path.read_text(encoding="utf-8"))
    assert [seat["file_uri"] for seat in seats["seats"]] == [
        "file:///coworld/players/0/file",
        "file:///coworld/players/1/file",
    ]


def test_game_hosted_local_runner_requires_one_source_per_seat(monkeypatch, tmp_path: Path) -> None:
    job = _game_hosted_job([b"first", b"second"])
    source = tmp_path / "source"
    source.write_bytes(b"first")
    monkeypatch.setattr(runner_module, "assert_episode_images_reachable", lambda _job: None)

    with pytest.raises(ValueError, match="requires 2 player file paths"):
        runner_module.run_coworld_episode(
            job,
            EpisodeArtifacts.create(tmp_path / "work"),
            timeout_seconds=30,
            player_file_paths=[source],
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


class _StillRunning:
    """A game process that never exits on its own."""

    returncode = None

    def poll(self):
        return None


class _Exited:
    def __init__(self, return_code: int) -> None:
        self.returncode = return_code

    def poll(self):
        return self.returncode


def test_game_hosted_local_run_collects_on_results_without_waiting_for_exit(tmp_path):
    artifacts = EpisodeArtifacts.create(tmp_path / "work")
    artifacts.results_path.write_text("{}", encoding="utf-8")
    artifacts.game_stderr_path.write_text("", encoding="utf-8")

    runner_module._wait_for_game_results_or_exit(
        _StillRunning(),  # type: ignore[arg-type]
        artifacts,
        (artifacts.results_path,),
        player_count=1,
        timeout_seconds=1.0,
    )


def test_game_hosted_local_run_reports_a_game_that_exits_without_results(tmp_path):
    artifacts = EpisodeArtifacts.create(tmp_path / "work")
    artifacts.game_stderr_path.write_text("boom", encoding="utf-8")

    with pytest.raises(runner_module.RunnerEpisodeError) as exc_info:
        runner_module._wait_for_game_results_or_exit(
            _Exited(3),  # type: ignore[arg-type]
            artifacts,
            (artifacts.results_path,),
            player_count=1,
            timeout_seconds=1.0,
        )

    assert exc_info.value.error_type == "game_unhealthy"


@pytest.mark.parametrize("process", [_StillRunning(), _Exited(3)], ids=["still-running", "exited-nonzero"])
def test_game_hosted_local_run_attributes_a_declared_player_failure(tmp_path, process):
    artifacts = EpisodeArtifacts.create(tmp_path / "work")
    artifacts.game_stderr_path.write_text("", encoding="utf-8")
    artifacts.player_failure_path.write_text(
        json.dumps({"failed_policy_index": 1, "message": "seat 1 crashed"}), encoding="utf-8"
    )

    with pytest.raises(runner_module.RunnerEpisodeError) as exc_info:
        runner_module._wait_for_game_results_or_exit(
            process,  # type: ignore[arg-type]
            artifacts,
            (artifacts.results_path,),
            player_count=2,
            timeout_seconds=1.0,
        )

    assert exc_info.value.error_type == "player_error"
    assert exc_info.value.failed_policy_index == 1


def test_game_hosted_local_run_reports_a_clean_exit_without_results(tmp_path):
    artifacts = EpisodeArtifacts.create(tmp_path / "work")
    artifacts.game_stderr_path.write_text("", encoding="utf-8")

    with pytest.raises(runner_module.RunnerEpisodeError) as exc_info:
        runner_module._wait_for_game_results_or_exit(
            _Exited(0),  # type: ignore[arg-type]
            artifacts,
            (artifacts.results_path,),
            player_count=1,
            timeout_seconds=1.0,
        )

    assert exc_info.value.error_type == "results_missing"


def test_game_hosted_local_run_times_out_when_results_never_appear(tmp_path):
    artifacts = EpisodeArtifacts.create(tmp_path / "work")
    artifacts.game_stderr_path.write_text("", encoding="utf-8")

    with pytest.raises(runner_module.RunnerEpisodeError) as exc_info:
        runner_module._wait_for_game_results_or_exit(
            _StillRunning(),  # type: ignore[arg-type]
            artifacts,
            (artifacts.results_path,),
            player_count=1,
            timeout_seconds=0.3,
        )

    assert exc_info.value.error_type == "episode_timeout"
