from __future__ import annotations

import asyncio
import json
import os
import secrets
import subprocess
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping
from urllib.parse import urlencode

from coworld.certifier import (
    CoworldPackage,
    build_manifest_episode_job_spec,
    load_coworld_package,
    load_results,
)
from coworld.runner.runner import (
    CONFIG_ENV_VAR,
    CONTAINER_WORKDIR,
    LOCAL_DOCKER_NETWORK,
    LOCAL_GAME_NETWORK_ALIAS_PREFIX,
    REPLAY_SAVE_ENV_VAR,
    REPLAY_SERVER_ENV_VAR,
    RESULTS_ENV_VAR,
    EpisodeArtifacts,
    PlayerLaunchSpec,
    RunnableLaunchSpec,
    _free_local_port,
    _player_container_ws_url,
    _require_replay_message,
    _tail,
    _wait_for_health,
    _wait_for_player_exit,
    assert_docker_image_reachable,
    ensure_local_docker_network,
    finalize_replay_artifacts,
    generate_tokens,
    replay_client_url,
    replay_session_path,
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
    variant_id: str
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


@dataclass(frozen=True)
class BedrockAwsEnv:
    access_key_id: str
    secret_access_key: str
    session_token: str | None
    region: str

    @property
    def container_env(self) -> dict[str, str]:
        env = {
            "USE_BEDROCK": "true",
            "AWS_ACCESS_KEY_ID": self.access_key_id,
            "AWS_SECRET_ACCESS_KEY": self.secret_access_key,
            "AWS_REGION": self.region,
            "AWS_DEFAULT_REGION": self.region,
        }
        if self.session_token is not None:
            env["AWS_SESSION_TOKEN"] = self.session_token
        return env


def play_coworld(
    manifest_path: Path,
    *,
    variant_id: str | None = None,
    player_images: list[str] | None = None,
    player_run: list[str] | None = None,
    use_bedrock: bool = False,
    aws_profile: str | None = None,
    aws_region: str | None = None,
    workspace: Path | None = None,
    timeout_seconds: float = 60.0,
    on_ready: Callable[[PlaySession], None],
) -> PlayResult:
    package = load_coworld_package(manifest_path)
    assert_docker_image_reachable(package.cogame.image, label="Cogame runnable.image")
    artifacts = EpisodeArtifacts.create(workspace, prefix="coworld-play-")
    if variant_id is None:
        variant_id = (
            "default"
            if any(variant.id == "default" for variant in package.manifest.variants)
            else package.manifest.variants[0].id
        )
    job_spec = build_manifest_episode_job_spec(
        package,
        variant_id=variant_id,
        player_images=player_images,
        player_run=player_run,
    )
    tokens = generate_tokens(len(job_spec.players))
    write_coworld_game_config(job_spec, artifacts, tokens)
    players = [PlayerLaunchSpec.from_model(player) for player in job_spec.players]
    game_port = _free_local_port()
    session = PlaySession(
        package=package,
        artifacts=artifacts,
        variant_id=variant_id,
        links=build_play_links(players, tokens, game_port=game_port),
    )

    run_id = secrets.token_hex(8)
    game_network_alias = f"{LOCAL_GAME_NETWORK_ALIAS_PREFIX}{run_id}"
    game_container = f"coworld-play-game-{run_id}"
    player_containers: list[str] = []
    player_processes: list[tuple[subprocess.Popen[str], Path]] = []
    ensure_local_docker_network()
    try:
        bedrock_container_env = (
            _resolve_bedrock_aws_env(aws_profile=aws_profile, aws_region=aws_region).container_env
            if use_bedrock
            else {}
        )
        bedrock_env_args = [arg for key in bedrock_container_env for arg in ("-e", key)]
        player_subprocess_env = {**os.environ, **bedrock_container_env} if bedrock_container_env else None
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

            for slot, player in enumerate(players):
                container_name = f"coworld-play-player-{run_id}-{slot}"
                engine_ws_url = _player_container_ws_url(game_network_alias, slot, tokens[slot], player)
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
                                *_env_args(player.env),
                                *bedrock_env_args,
                                "-e",
                                f"COGAMES_ENGINE_WS_URL={engine_ws_url}",
                                *_image_command(player),
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
            return_code = game_process.wait()
            if return_code != 0:
                raise RuntimeError(
                    f"Game container exited with status {return_code}.\n{_tail(artifacts.game_stderr_path)}"
                )

            for player_process, player_log_path in player_processes:
                _wait_for_player_exit(player_process, player_log_path)
            finalize_replay_artifacts(artifacts)
    finally:
        for container_name in player_containers:
            subprocess.run(["docker", "rm", "-f", container_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["docker", "rm", "-f", game_container], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    return PlayResult(session=session, results=load_results(package, artifacts))


def _resolve_bedrock_aws_env(*, aws_profile: str | None, aws_region: str | None) -> BedrockAwsEnv:
    command = ["aws", "configure", "export-credentials", "--format", "process"]
    if aws_profile is not None:
        command.extend(["--profile", aws_profile])
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    exported = json.loads(result.stdout)
    if "AccessKeyId" not in exported or "SecretAccessKey" not in exported:
        raise RuntimeError(
            "aws configure export-credentials did not return AWS credentials. "
            "Ensure your AWS profile is configured (try: aws sso login)."
        )

    region = _resolve_bedrock_aws_region(aws_profile=aws_profile, aws_region=aws_region)
    return BedrockAwsEnv(
        access_key_id=exported["AccessKeyId"],
        secret_access_key=exported["SecretAccessKey"],
        session_token=exported.get("SessionToken"),
        region=region,
    )


def _resolve_bedrock_aws_region(*, aws_profile: str | None, aws_region: str | None) -> str:
    region = aws_region or os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
    if region:
        return region

    command = ["aws", "configure", "get", "region"]
    if aws_profile is not None:
        command.extend(["--profile", aws_profile])
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if region := result.stdout.strip():
        return region
    raise RuntimeError("AWS region required for --use-bedrock. Pass --aws-region or set AWS_REGION/AWS_DEFAULT_REGION.")


def replay_coworld(
    manifest_path: Path,
    replay_path: Path,
    *,
    workspace: Path | None = None,
    timeout_seconds: float = 60.0,
    verify_replay: bool = False,
    on_ready: Callable[[ReplaySession], None],
) -> ReplaySession:
    package = load_coworld_package(manifest_path)
    assert_docker_image_reachable(package.cogame.image, label="Cogame runnable.image")
    replay_path = replay_path.resolve()
    if not replay_path.is_file():
        raise FileNotFoundError(f"Replay file does not exist or is not a file: {replay_path}")

    artifacts = EpisodeArtifacts.create(workspace, prefix="coworld-replay-")
    replay_port = _free_local_port()
    container_replay_uri = f"file:///coworld-replay/{replay_path.name}"
    session = ReplaySession(
        package=package,
        artifacts=artifacts,
        replay_path=replay_path,
        link=replay_client_url(replay_port, container_replay_uri),
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
                    f"127.0.0.1:{replay_port}:8080",
                    *_env_args(package.cogame.env),
                    "-e",
                    f"{REPLAY_SERVER_ENV_VAR}=1",
                    "-v",
                    f"{replay_path.parent}:/coworld-replay:ro",
                    *_image_command(package.cogame),
                ],
                stdout=game_stdout,
                stderr=game_stderr,
                text=True,
            )

            _wait_for_health(replay_port, replay_process, artifacts.game_stderr_path, timeout_seconds=timeout_seconds)
            if verify_replay:
                probe_url = f"ws://127.0.0.1:{replay_port}{replay_session_path(container_replay_uri)}"
                try:
                    asyncio.run(_require_replay_message(probe_url, timeout_seconds=timeout_seconds))
                except Exception as probe_error:
                    raise RuntimeError(
                        f"Replay container did not enter replay-server mode "
                        f"(no frame from {probe_url} within {timeout_seconds:.1f}s for uri={container_replay_uri}). "
                        f"The game image may not implement COGAME_REPLAY_SERVER=1, "
                        f"or the replay file may not be reachable inside the container. "
                        f"See packages/coworld/src/coworld/GAME_RUNTIME_README.md for the contract."
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
        f"http://127.0.0.1:{game_port}/clients/player?{_player_query(slot, tokens[slot], player)}"
        for slot, player in enumerate(players)
    ]
    return PlayLinks(
        players=player_links,
        global_=f"http://127.0.0.1:{game_port}/clients/global",
        admin=f"http://127.0.0.1:{game_port}/clients/admin",
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
