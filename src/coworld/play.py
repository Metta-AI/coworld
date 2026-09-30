from __future__ import annotations

import asyncio
import os
import secrets
import subprocess
import threading
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, cast
from urllib.parse import urlencode

from coworld.certifier import (
    CoworldPackage,
    build_manifest_episode_job_spec,
    load_coworld_package,
    load_manifest_episode_job_spec,
    load_results,
)
from coworld.replay_viewer import LocalReplayViewerServer, source_replay_viewer_bundle
from coworld.runner.runner import (
    CONFIG_ENV_VAR,
    CONTAINER_WORKDIR,
    DEFAULT_PLAYER_EXIT_TIMEOUT_SECONDS,
    GAME_HOST,
    GAME_HOST_ENV_VAR,
    GAME_PORT,
    GAME_PORT_ENV_VAR,
    LOCAL_DOCKER_NETWORK,
    LOCAL_GAME_NETWORK_ALIAS_PREFIX,
    PLAYER_FAILURE_ENV_VAR,
    REPLAY_LOAD_ENV_VAR,
    REPLAY_SAVE_ENV_VAR,
    RESULTS_ENV_VAR,
    EpisodeArtifacts,
    PlayerLaunchSpec,
    ResolvedLocalPort,
    _free_local_port,
    _player_container_ws_url,
    _raise_if_game_declared_player_failure,
    _require_replay_message,
    _tail,
    _wait_for_game_exit,
    _wait_for_health,
    _wait_for_player_exit,
    assert_docker_image_reachable,
    assert_episode_images_reachable,
    docker_env_args,
    docker_image_command,
    ensure_local_docker_network,
    game_env_with_resolved_local_ports,
    generate_tokens,
    local_port_publish_args,
    replay_client_url,
    replay_session_path,
    resolve_local_extra_ports,
    write_coworld_game_config,
)
from coworld.schema_validation import JsonObject
from coworld.types import CoworldHumanPlayerSpec, CoworldRunnableSpec


@dataclass(frozen=True)
class PlayLinks:
    players: list[str]
    global_: str
    admin: str


@dataclass(frozen=True)
class PlaySession:
    package: CoworldPackage
    artifacts: EpisodeArtifacts
    variant_id: str
    links: PlayLinks
    local_ports: list[ResolvedLocalPort]


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
    variant_id: str | None = None,
    episode_request_path: Path | None = None,
    player_images: list[str] | None = None,
    player_run: list[str] | None = None,
    use_llm: bool = False,
    secret_env: Mapping[str, str] | None = None,
    workspace: Path | None = None,
    timeout_seconds: float = 3600.0,
    player_exit_timeout_seconds: float = DEFAULT_PLAYER_EXIT_TIMEOUT_SECONDS,
    on_ready: Callable[[PlaySession], None],
) -> PlayResult:
    package = load_coworld_package(manifest_path, tolerate_newer_fields=True)
    if package.manifest.game.player_runtime == "game-hosted":
        raise ValueError("coworld play does not support game-hosted Coworlds")
    artifacts = EpisodeArtifacts.create(workspace, prefix="coworld-play-")
    if episode_request_path is not None and (variant_id is not None or player_images or player_run):
        raise ValueError("episode_request_path cannot be combined with variant_id, player_images, or player_run")
    if episode_request_path is not None:
        job_spec = load_manifest_episode_job_spec(package, episode_request_path)
        variant_label = "episode-request"
    else:
        job_spec = build_manifest_episode_job_spec(
            package,
            variant_id=variant_id,
            player_images=player_images,
            player_run=player_run,
        )
        variant_label = variant_id if variant_id is not None else "certification"
    if any(isinstance(player, CoworldHumanPlayerSpec) for player in job_spec.players):
        raise ValueError("Human player seats require the hosted Kubernetes episode runner")
    assert_episode_images_reachable(job_spec)
    tokens = generate_tokens(len(job_spec.players))
    write_coworld_game_config(job_spec, artifacts, tokens)
    players = [PlayerLaunchSpec.from_model(player) for player in cast(list[CoworldRunnableSpec], job_spec.players)]
    game_port = _free_local_port()
    local_ports = resolve_local_extra_ports(
        package.game.env,
        reserved_host_ports={game_port},
        allocate_port=_free_local_port,
    )
    game_env = game_env_with_resolved_local_ports(package.game.env, local_ports)
    session = PlaySession(
        package=package,
        artifacts=artifacts,
        variant_id=variant_label,
        links=build_play_links(players, tokens, game_port=game_port),
        local_ports=local_ports,
    )

    run_id = secrets.token_hex(8)
    game_network_alias = f"{LOCAL_GAME_NETWORK_ALIAS_PREFIX}{run_id}"
    game_container = f"coworld-play-game-{run_id}"
    player_containers: list[str] = []
    player_processes: list[tuple[subprocess.Popen[str], Path]] = []
    ensure_local_docker_network()
    try:
        llm_container_env = _resolve_local_llm_env() if use_llm else {}
        combined_secret_env = {**llm_container_env, **(secret_env or {})}
        secret_env_args = [arg for key in combined_secret_env for arg in ("-e", key)]
        player_subprocess_env = {**os.environ, **combined_secret_env} if combined_secret_env else None
        with ExitStack() as stack:
            game_stdout = stack.enter_context(artifacts.game_stdout_path.open("w"))
            game_stderr = stack.enter_context(artifacts.game_stderr_path.open("w"))
            game_process = subprocess.Popen(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--name",
                    game_container,
                    "--network",
                    LOCAL_DOCKER_NETWORK,
                    "--network-alias",
                    game_network_alias,
                    "-p",
                    f"127.0.0.1:{game_port}:{GAME_PORT}",
                    *local_port_publish_args(local_ports),
                    *docker_env_args(game_env),
                    "-e",
                    f"{GAME_HOST_ENV_VAR}={GAME_HOST}",
                    "-e",
                    f"{GAME_PORT_ENV_VAR}={GAME_PORT}",
                    "-e",
                    f"{CONFIG_ENV_VAR}=file://{CONTAINER_WORKDIR}/config.json",
                    "-e",
                    f"{RESULTS_ENV_VAR}=file://{CONTAINER_WORKDIR}/results.json",
                    "-e",
                    f"{REPLAY_SAVE_ENV_VAR}=file://{CONTAINER_WORKDIR}/replay",
                    "-e",
                    f"{PLAYER_FAILURE_ENV_VAR}=file://{CONTAINER_WORKDIR}/player_failure.json",
                    "-v",
                    f"{artifacts.workspace}:{CONTAINER_WORKDIR}:rw",
                    *docker_image_command(package.game),
                ],
                stdout=game_stdout,
                stderr=game_stderr,
                text=True,
            )

            _wait_for_health(game_port, game_process, artifacts.game_stderr_path, timeout_seconds=timeout_seconds)

            for slot, player in enumerate(players):
                container_name = f"coworld-play-player-{run_id}-{slot}"
                engine_ws_url = _player_container_ws_url(game_network_alias, slot, tokens[slot])
                player_containers.append(container_name)
                player_log_path = artifacts.policy_log_path(slot)
                player_log = stack.enter_context(player_log_path.open("w"))
                player_processes.append(
                    (
                        subprocess.Popen(
                            [
                                "docker",
                                "run",
                                "--rm",
                                "--name",
                                container_name,
                                "--network",
                                LOCAL_DOCKER_NETWORK,
                                *docker_env_args(player.env),
                                *secret_env_args,
                                "-e",
                                f"COWORLD_PLAYER_WS_URL={engine_ws_url}",
                                "-e",
                                f"COGAMES_ENGINE_WS_URL={engine_ws_url}",
                                *docker_image_command(player),
                            ],
                            stdout=player_log,
                            stderr=subprocess.STDOUT,
                            text=True,
                            env=player_subprocess_env,
                        ),
                        player_log_path,
                    )
                )

            on_ready(session)
            _wait_for_game_exit(game_process, artifacts.game_stderr_path, timeout_seconds=timeout_seconds)
            _raise_if_game_declared_player_failure(artifacts, (artifacts.results_path,), player_count=len(players))

            for slot, (player_process, player_log_path) in enumerate(player_processes):
                _wait_for_player_exit(
                    player_process,
                    player_log_path,
                    failed_policy_index=slot,
                    timeout_seconds=player_exit_timeout_seconds,
                )
    finally:
        for container_name in player_containers:
            subprocess.run(["docker", "rm", "-f", container_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["docker", "rm", "-f", game_container], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    return PlayResult(session=session, results=load_results(package, artifacts))


def _resolve_local_llm_env() -> dict[str, str]:
    """Forward local model access through inherited Docker environment, not argv."""
    endpoint = os.environ.get("COWORLD_LLM_ENDPOINT")
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not endpoint and not api_key:
        raise RuntimeError("--use-llm requires COWORLD_LLM_ENDPOINT or OPENROUTER_API_KEY in the host environment")
    env = {"COWORLD_LLM_ENABLED": "true"}
    if endpoint:
        env["COWORLD_LLM_ENDPOINT"] = endpoint
    else:
        env["OPENROUTER_API_KEY"] = os.environ["OPENROUTER_API_KEY"]
    if model := os.environ.get("COWORLD_LLM_MODEL"):
        env["COWORLD_LLM_MODEL"] = model
    return env


def replay_coworld(
    manifest_path: Path,
    replay_path: Path,
    *,
    workspace: Path | None = None,
    timeout_seconds: float = 60.0,
    verify_replay: bool = False,
    on_ready: Callable[[ReplaySession], None],
) -> ReplaySession:
    package = load_coworld_package(manifest_path, tolerate_newer_fields=True)
    replay_path = replay_path.resolve()
    if not replay_path.is_file():
        raise FileNotFoundError(f"Replay file does not exist or is not a file: {replay_path}")

    artifacts = EpisodeArtifacts.create(workspace, prefix="coworld-replay-")
    if replay_viewer := package.manifest.game.replay_viewer:
        bundle_dir = source_replay_viewer_bundle(package.manifest_path.parent, replay_viewer.bundle)
        with LocalReplayViewerServer(bundle_dir, replay_path, port=0) as server:
            server_thread = threading.Thread(target=server.serve_forever, name="coworld-replay-viewer", daemon=True)
            server_thread.start()
            session = ReplaySession(
                package=package,
                artifacts=artifacts,
                replay_path=replay_path,
                link=server.viewer_url,
            )
            try:
                on_ready(session)
                server_thread.join()
            finally:
                server.shutdown()
                server_thread.join()
        return session

    assert_docker_image_reachable(package.game.image, label="game.runnable.image")
    replay_port = _free_local_port()
    container_replay_uri = f"file:///coworld-replay/{replay_path.name}"
    session = ReplaySession(
        package=package,
        artifacts=artifacts,
        replay_path=replay_path,
        link=replay_client_url(replay_port),
    )

    replay_container = f"coworld-replay-game-{secrets.token_hex(8)}"
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
                    f"127.0.0.1:{replay_port}:{GAME_PORT}",
                    *docker_env_args(package.game.env),
                    "-e",
                    f"{GAME_HOST_ENV_VAR}={GAME_HOST}",
                    "-e",
                    f"{GAME_PORT_ENV_VAR}={GAME_PORT}",
                    "-e",
                    f"{REPLAY_LOAD_ENV_VAR}={container_replay_uri}",
                    "-v",
                    f"{replay_path.parent}:/coworld-replay:ro",
                    *docker_image_command(package.game),
                ],
                stdout=game_stdout,
                stderr=game_stderr,
                text=True,
            )

            _wait_for_health(replay_port, replay_process, artifacts.game_stderr_path, timeout_seconds=timeout_seconds)
            if verify_replay:
                probe_url = f"ws://127.0.0.1:{replay_port}{replay_session_path()}"
                try:
                    asyncio.run(_require_replay_message(probe_url, timeout_seconds=timeout_seconds))
                except Exception as probe_error:
                    raise RuntimeError(
                        f"Replay container did not enter replay mode "
                        f"(no frame from {probe_url} within {timeout_seconds:.1f}s "
                        f"for {REPLAY_LOAD_ENV_VAR}={container_replay_uri}). "
                        f"The game image may not implement {REPLAY_LOAD_ENV_VAR}, "
                        f"or the replay file may not be reachable inside the container. "
                        f"See packages/coworld/src/coworld/docs/roles/GAME.md for the contract."
                    ) from probe_error
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
        f"http://127.0.0.1:{game_port}/client/player?{_player_query(slot, tokens[slot])}"
        for slot, _player in enumerate(players)
    ]
    return PlayLinks(
        players=player_links,
        global_=f"http://127.0.0.1:{game_port}/client/global",
        admin=f"http://127.0.0.1:{game_port}/client/admin",
    )


def _player_query(slot: int, token: str) -> str:
    return urlencode({"slot": slot, "token": token})
