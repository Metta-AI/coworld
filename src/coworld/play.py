from __future__ import annotations

import json
import secrets
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, cast
from urllib.parse import urlencode

from coworld.certifier import (
    CoworldPackage,
    build_episode_request,
    build_game_config,
    build_player_launch_specs,
    load_coworld_package,
    load_results,
)
from coworld.episode_runner import (
    CONTAINER_WORKDIR,
    EpisodeArtifacts,
    PlayerLaunchSpec,
    _free_local_port,
    _tail,
    _wait_for_health,
    assert_docker_image_reachable,
)
from coworld.schema_validation import JsonObject


@dataclass(frozen=True)
class PlayLinks:
    players: list[str]
    global_: str


@dataclass(frozen=True)
class PlaySession:
    package: CoworldPackage
    artifacts: EpisodeArtifacts
    links: PlayLinks


@dataclass(frozen=True)
class PlayResult:
    session: PlaySession
    results: JsonObject


def play_coworld(
    manifest_path: Path,
    *,
    workspace: Path | None = None,
    timeout_seconds: float = 60.0,
    on_ready: Callable[[PlaySession], None],
) -> PlayResult:
    package = load_coworld_package(manifest_path)
    assert_docker_image_reachable(package.cogame_image, label="Cogame image_uri")
    artifacts = EpisodeArtifacts.create(workspace, prefix="coworld-play-")
    tokens = [secrets.token_urlsafe(16) for _ in cast(list[object], package.certification["players"])]
    game_config = build_game_config(package, tokens)
    artifacts.config_path.write_text(json.dumps(game_config, indent=2))
    episode_request = build_episode_request(package, artifacts)
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
                    "-e",
                    f"COGAME_CONFIG_PATH={CONTAINER_WORKDIR}/config.json",
                    "-e",
                    f"COGAME_RESULTS_PATH={CONTAINER_WORKDIR}/results.json",
                    "-e",
                    f"COGAME_SAVE_REPLAY_PATH={CONTAINER_WORKDIR}/replay.json",
                    "-v",
                    f"{artifacts.workspace.resolve()}:{CONTAINER_WORKDIR}:rw",
                    package.cogame_image,
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
    )


def _player_query(slot: int, token: str, player: PlayerLaunchSpec) -> str:
    query = {"slot": slot, "token": token}
    query.update(player.initial_params)
    return urlencode(query)
