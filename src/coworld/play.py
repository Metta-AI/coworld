from __future__ import annotations

import secrets
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping
from urllib.parse import urlencode

from coworld.certifier import (
    CoworldPackage,
    build_coworld_episode_job_spec,
    build_episode_request,
    build_player_launch_specs,
    load_coworld_package,
    load_results,
)
from coworld.runner.runner import (
    CONFIG_ENV_VAR,
    CONTAINER_WORKDIR,
    REPLAY_LOAD_ENV_VAR,
    REPLAY_SAVE_ENV_VAR,
    RESULTS_ENV_VAR,
    EpisodeArtifacts,
    PlayerLaunchSpec,
    RunnableLaunchSpec,
    _free_local_port,
    _replay_client_url,
    _tail,
    _wait_for_health,
    assert_docker_image_reachable,
    generate_tokens,
    write_coworld_game_config,
)
from coworld.schema_validation import JsonObject


@dataclass(frozen=True)
class PlayLinks:
    players: list[str]
    global_: str
    admin: str


@dataclass(frozen=True)
class PlaySession:
    package: CoworldPackage
    artifacts: EpisodeArtifacts
    links: PlayLinks


@dataclass(frozen=True)
class PlayResult:
    session: PlaySession
    results: JsonObject


@dataclass(frozen=True)
class ReplaySession:
    package: CoworldPackage
    artifacts: EpisodeArtifacts
    replay_path: Path
    link: str


def play_coworld(
    manifest_path: Path,
    *,
    workspace: Path | None = None,
    timeout_seconds: float = 60.0,
    on_ready: Callable[[PlaySession], None],
) -> PlayResult:
    package = load_coworld_package(manifest_path, validate_files=False)
    assert_docker_image_reachable(package.cogame.image, label="Cogame runnable.image")
    artifacts = EpisodeArtifacts.create(workspace, prefix="coworld-play-")
    episode_request = build_episode_request(package, artifacts)
    job_spec = build_coworld_episode_job_spec(episode_request)
    tokens = generate_tokens(len(job_spec.players))
    write_coworld_game_config(job_spec, artifacts, tokens)
    players = build_player_launch_specs(episode_request)
    game_port = _free_local_port()
    session = PlaySession(
        package=package,
        artifacts=artifacts,
        links=build_play_links(players, tokens, game_port=game_port),
    )

    game_container = f"coworld-play-game-{secrets.token_hex(8)}"
    try:
        with artifacts.game_stdout_path.open("w") as game_stdout, artifacts.game_stderr_path.open("w") as game_stderr:
            game_process = subprocess.Popen(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--name",
                    game_container,
                    "-p",
                    f"127.0.0.1:{game_port}:8080",
                    *_env_args(package.cogame.env),
                    "-e",
                    f"{CONFIG_ENV_VAR}=file://{CONTAINER_WORKDIR}/config.json",
                    "-e",
                    f"{RESULTS_ENV_VAR}=file://{CONTAINER_WORKDIR}/results.json",
                    "-e",
                    f"{REPLAY_SAVE_ENV_VAR}=file://{CONTAINER_WORKDIR}/replay.json",
                    "-v",
                    f"{artifacts.workspace.resolve()}:{CONTAINER_WORKDIR}:rw",
                    *_image_command(package.cogame),
                ],
                stdout=game_stdout,
                stderr=game_stderr,
                text=True,
            )

            _wait_for_health(game_port, game_process, artifacts.game_stderr_path, timeout_seconds=timeout_seconds)
            on_ready(session)
            return_code = game_process.wait()
            if return_code != 0:
                raise RuntimeError(
                    f"Game container exited with status {return_code}.\n{_tail(artifacts.game_stderr_path)}"
                )
    finally:
        subprocess.run(["docker", "rm", "-f", game_container], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    return PlayResult(session=session, results=load_results(package, artifacts))


def replay_coworld(
    manifest_path: Path,
    replay_path: Path,
    *,
    workspace: Path | None = None,
    timeout_seconds: float = 60.0,
    on_ready: Callable[[ReplaySession], None],
) -> ReplaySession:
    package = load_coworld_package(manifest_path, validate_files=False)
    assert_docker_image_reachable(package.cogame.image, label="Cogame runnable.image")
    replay_path = replay_path.resolve()
    if not replay_path.is_file():
        raise FileNotFoundError(f"Replay file does not exist or is not a file: {replay_path}")

    artifacts = EpisodeArtifacts.create(workspace, prefix="coworld-replay-")
    replay_port = _free_local_port()
    session = ReplaySession(
        package=package,
        artifacts=artifacts,
        replay_path=replay_path,
        link=_replay_client_url(replay_port),
    )

    replay_container = f"coworld-replay-game-{secrets.token_hex(8)}"
    container_replay_path = f"/coworld-replay/{replay_path.name}"
    try:
        with artifacts.game_stdout_path.open("w") as game_stdout, artifacts.game_stderr_path.open("w") as game_stderr:
            replay_process = subprocess.Popen(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--name",
                    replay_container,
                    "-p",
                    f"127.0.0.1:{replay_port}:8080",
                    *_env_args(package.cogame.env),
                    "-e",
                    f"{REPLAY_LOAD_ENV_VAR}=file://{container_replay_path}",
                    "-v",
                    f"{replay_path.parent}:/coworld-replay:ro",
                    *_image_command(package.cogame),
                ],
                stdout=game_stdout,
                stderr=game_stderr,
                text=True,
            )

            _wait_for_health(replay_port, replay_process, artifacts.game_stderr_path, timeout_seconds=timeout_seconds)
            on_ready(session)
            return_code = replay_process.wait()
            if return_code != 0:
                raise RuntimeError(
                    f"Replay container exited with status {return_code}.\n{_tail(artifacts.game_stderr_path)}"
                )
    finally:
        subprocess.run(["docker", "rm", "-f", replay_container], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    return session


def build_play_links(
    players: list[PlayerLaunchSpec],
    tokens: list[str],
    *,
    game_port: int,
) -> PlayLinks:
    player_links = [
        f"http://127.0.0.1:{game_port}/player?{_player_query(slot, tokens[slot], player)}"
        for slot, player in enumerate(players)
    ]
    return PlayLinks(
        players=player_links,
        global_=f"http://127.0.0.1:{game_port}/global",
        admin=f"http://127.0.0.1:{game_port}/admin",
    )


def _player_query(slot: int, token: str, player: PlayerLaunchSpec) -> str:
    return urlencode({"slot": slot, "token": token})


def _env_args(env: Mapping[str, str]) -> list[str]:
    args: list[str] = []
    for key, value in env.items():
        args.extend(["-e", f"{key}={value}"])
    return args


def _image_command(runnable: RunnableLaunchSpec) -> list[str]:
    if not runnable.run:
        return [runnable.image]
    return ["--entrypoint", runnable.run[0], runnable.image, *runnable.run[1:]]
