from __future__ import annotations

import asyncio
import json
import secrets
import socket
import subprocess
import tempfile
import time
import zlib
from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, cast
from urllib.parse import urlencode

import httpx
import websockets
from websockets.exceptions import InvalidHandshake, InvalidStatus

from coworld.schema_validation import validate_json_schema
from coworld.types import CoworldEpisodeJobSpec, CoworldPlayerSpec, CoworldRunnableSpec

CONTAINER_WORKDIR = "/coworld"
CONFIG_ENV_VAR = "COGAME_CONFIG_URI"
RESULTS_ENV_VAR = "COGAME_RESULTS_URI"
REPLAY_SAVE_ENV_VAR = "COGAME_SAVE_REPLAY_URI"
REPLAY_SERVER_ENV_VAR = "COGAME_REPLAY_SERVER"


@dataclass(frozen=True)
class EpisodeArtifacts:
    workspace: Path
    config_path: Path
    results_path: Path
    replay_path: Path
    logs_dir: Path
    game_stdout_path: Path
    game_stderr_path: Path

    @classmethod
    def create(cls, workspace: Path | None = None, *, prefix: str = "coworld-cert-") -> EpisodeArtifacts:
        workspace = workspace or _new_workspace(prefix)
        workspace.mkdir(parents=True, exist_ok=True)
        logs_dir = workspace / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        return cls(
            workspace=workspace,
            config_path=workspace / "config.json",
            results_path=workspace / "results.json",
            replay_path=workspace / "replay.json",
            logs_dir=logs_dir,
            game_stdout_path=logs_dir / "game.stdout.log",
            game_stderr_path=logs_dir / "game.stderr.log",
        )

    def policy_log_path(self, slot: int) -> Path:
        return self.logs_dir / f"policy_agent_{slot}.txt"


@dataclass(frozen=True)
class EpisodeRunSpec:
    cogame: RunnableLaunchSpec
    players: list[PlayerLaunchSpec]
    tokens: list[str]
    artifacts: EpisodeArtifacts
    timeout_seconds: float


@dataclass(frozen=True)
class RunnableLaunchSpec:
    image: str
    run: tuple[str, ...] = ()
    env: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def from_runnable(cls, runnable: Mapping[str, object]) -> RunnableLaunchSpec:
        run: tuple[str, ...] = ()
        env: Mapping[str, str] = {}
        if "run" in runnable:
            run = tuple(cast(list[str], runnable["run"]))
        if "env" in runnable:
            env = cast(Mapping[str, str], runnable["env"])
        return cls(image=cast(str, runnable["image"]), run=run, env=env)

    @classmethod
    def from_model(cls, runnable: CoworldRunnableSpec) -> RunnableLaunchSpec:
        return cls(image=runnable.image, run=tuple(runnable.run), env=runnable.env)


@dataclass(frozen=True)
class PlayerLaunchSpec(RunnableLaunchSpec):
    @classmethod
    def from_model(cls, player: CoworldPlayerSpec) -> PlayerLaunchSpec:
        runnable = RunnableLaunchSpec.from_model(player)
        return cls(
            image=runnable.image,
            run=runnable.run,
            env=runnable.env,
        )


def assert_docker_image_reachable(image: str, *, label: str = "Docker image") -> None:
    local_result = subprocess.run(["docker", "image", "inspect", image], capture_output=True, text=True, timeout=30)
    if local_result.returncode == 0:
        return

    remote_result = subprocess.run(["docker", "manifest", "inspect", image], capture_output=True, text=True, timeout=60)
    if remote_result.returncode == 0:
        return

    raise RuntimeError(
        f"{label} is not available locally or reachable remotely: {image}\n"
        f"docker image inspect stderr:\n{local_result.stderr[-2000:]}\n"
        f"docker manifest inspect stderr:\n{remote_result.stderr[-2000:]}"
    )


def run_coworld_episode(
    job: CoworldEpisodeJobSpec,
    artifacts: EpisodeArtifacts,
    *,
    timeout_seconds: float,
    verify_replay: bool = False,
) -> None:
    tokens = generate_tokens(len(job.players))
    write_coworld_game_config(job, artifacts, tokens)

    run_spec = EpisodeRunSpec(
        cogame=RunnableLaunchSpec.from_model(job.game_runnable),
        players=[PlayerLaunchSpec.from_model(player) for player in job.players],
        tokens=tokens,
        artifacts=artifacts,
        timeout_seconds=timeout_seconds,
    )
    run_cogame_episode(run_spec, verify_replay=verify_replay)

    results = json.loads(artifacts.results_path.read_text(encoding="utf-8"))
    validate_json_schema(results, job.results_schema)
    if artifacts.replay_path.exists():
        compress_replay(artifacts)


def generate_tokens(player_count: int) -> list[str]:
    return [secrets.token_urlsafe(16) for _ in range(player_count)]


def coworld_game_config(job: CoworldEpisodeJobSpec, tokens: list[str]) -> dict[str, object]:
    game_config = dict(job.game_config)
    game_config["tokens"] = tokens
    validate_json_schema(game_config, job.config_schema)
    return game_config


def write_coworld_game_config(job: CoworldEpisodeJobSpec, artifacts: EpisodeArtifacts, tokens: list[str]) -> None:
    game_config = coworld_game_config(job, tokens)
    artifacts.config_path.write_text(json.dumps(game_config, indent=2), encoding="utf-8")


def compress_replay(artifacts: EpisodeArtifacts) -> Path:
    compressed_path = artifacts.workspace / "replay.json.z"
    compressed_path.write_bytes(zlib.compress(artifacts.replay_path.read_bytes()))
    return compressed_path


def replay_session_path(replay_uri: str) -> str:
    return f"/replay?{urlencode({'uri': replay_uri})}"


def replay_client_url(port: int, replay_uri: str) -> str:
    return f"http://127.0.0.1:{port}/clients/replay?{urlencode({'uri': replay_uri})}"


def run_cogame_episode(spec: EpisodeRunSpec, *, verify_replay: bool = True) -> None:
    port = _free_local_port()
    run_id = secrets.token_hex(8)
    game_container = f"coworld-cert-game-{run_id}"
    replay_container = f"coworld-cert-replay-{run_id}"
    player_containers: list[str] = []
    player_processes: list[tuple[subprocess.Popen[str], Path]] = []

    try:
        with ExitStack() as stack:
            game_stdout = stack.enter_context(spec.artifacts.game_stdout_path.open("w"))
            game_stderr = stack.enter_context(spec.artifacts.game_stderr_path.open("w"))
            game_process = subprocess.Popen(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--name",
                    game_container,
                    "-p",
                    f"127.0.0.1:{port}:8080",
                    *_env_args(spec.cogame.env),
                    "-e",
                    f"{CONFIG_ENV_VAR}=file://{CONTAINER_WORKDIR}/config.json",
                    "-e",
                    f"{RESULTS_ENV_VAR}=file://{CONTAINER_WORKDIR}/results.json",
                    "-e",
                    f"{REPLAY_SAVE_ENV_VAR}=file://{CONTAINER_WORKDIR}/replay.json",
                    "-v",
                    f"{spec.artifacts.workspace.resolve()}:{CONTAINER_WORKDIR}:rw",
                    *_image_command(spec.cogame),
                ],
                stdout=game_stdout,
                stderr=game_stderr,
                text=True,
            )

            _wait_for_health(port, game_process, spec.artifacts.game_stderr_path, timeout_seconds=spec.timeout_seconds)
            if spec.players:
                _require_http_ok(_player_client_url(port, 0, spec.tokens[0], spec.players[0]))
                asyncio.run(_require_bad_player_rejected(f"ws://127.0.0.1:{port}/player?slot=0&token=bad"))
            _require_http_ok(f"http://127.0.0.1:{port}/clients/global")

            for slot, player in enumerate(spec.players):
                container_name = f"coworld-cert-player-{run_id}-{slot}"
                engine_ws_url = _player_container_ws_url(port, slot, spec.tokens[slot], player)
                player_containers.append(container_name)
                player_log_path = spec.artifacts.policy_log_path(slot)
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
                                "--add-host",
                                "host.docker.internal:host-gateway",
                                *_env_args(player.env),
                                "-e",
                                f"COGAMES_ENGINE_WS_URL={engine_ws_url}",
                                *_image_command(player),
                            ],
                            stdout=player_log,
                            stderr=subprocess.STDOUT,
                            text=True,
                        ),
                        player_log_path,
                    )
                )

            asyncio.run(_require_global_message(f"ws://127.0.0.1:{port}/global", timeout_seconds=spec.timeout_seconds))
            _wait_for_game_exit(game_process, spec.artifacts.game_stderr_path, timeout_seconds=spec.timeout_seconds)

            for player_process, player_stderr_path in player_processes:
                _wait_for_player_exit(player_process, player_stderr_path)

            if not verify_replay:
                return

            replay_port = _free_local_port()
            replay_uri = f"file://{CONTAINER_WORKDIR}/replay.json"
            replay_process = subprocess.Popen(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--name",
                    replay_container,
                    "-p",
                    f"127.0.0.1:{replay_port}:8080",
                    *_env_args(spec.cogame.env),
                    "-e",
                    f"{REPLAY_SERVER_ENV_VAR}=1",
                    "-v",
                    f"{spec.artifacts.workspace.resolve()}:{CONTAINER_WORKDIR}:rw",
                    *_image_command(spec.cogame),
                ],
                stdout=game_stdout,
                stderr=game_stderr,
                text=True,
            )
            _wait_for_health(
                replay_port,
                replay_process,
                spec.artifacts.game_stderr_path,
                timeout_seconds=spec.timeout_seconds,
            )
            _require_http_ok(replay_client_url(replay_port, replay_uri), allow_redirect=True)
            asyncio.run(
                _require_replay_message(
                    f"ws://127.0.0.1:{replay_port}{replay_session_path(replay_uri)}",
                    timeout_seconds=spec.timeout_seconds,
                )
            )
    finally:
        for container_name in player_containers:
            subprocess.run(["docker", "rm", "-f", container_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["docker", "rm", "-f", game_container], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["docker", "rm", "-f", replay_container], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _player_container_ws_url(port: int, slot: int, token: str, player: PlayerLaunchSpec) -> str:
    return f"ws://host.docker.internal:{port}/player?{_player_query(slot, token, player)}"


def _player_client_url(port: int, slot: int, token: str, player: PlayerLaunchSpec) -> str:
    return f"http://127.0.0.1:{port}/clients/player?{_player_query(slot, token, player)}"


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


def _require_http_ok(url: str, *, allow_redirect: bool = False) -> None:
    response = httpx.get(url, timeout=5.0)
    if allow_redirect and 300 <= response.status_code < 400:
        return
    response.raise_for_status()


async def _require_bad_player_rejected(url: str) -> None:
    rejected = False
    try:
        async with websockets.connect(url, open_timeout=5):
            pass
    except InvalidStatus as exc:
        rejected = exc.response.status_code in {401, 403}
        if not rejected:
            raise
    except InvalidHandshake:
        rejected = True
    if not rejected:
        raise AssertionError(f"Bad player token was accepted: {url}")


async def _require_global_message(url: str, *, timeout_seconds: float) -> None:
    async with websockets.connect(url, open_timeout=5) as websocket:
        message = await asyncio.wait_for(websocket.recv(), timeout=min(timeout_seconds, 10.0))
        if not message:
            raise AssertionError(f"Global viewer received an empty message from {url}")


async def _require_replay_message(url: str, *, timeout_seconds: float) -> None:
    async with websockets.connect(url, open_timeout=5, max_size=None) as websocket:
        message = await asyncio.wait_for(websocket.recv(), timeout=min(timeout_seconds, 10.0))
        if not message:
            raise AssertionError(f"Replay viewer received an empty message from {url}")


def _wait_for_health(
    port: int,
    game_process: subprocess.Popen[str],
    stderr_path: Path,
    *,
    timeout_seconds: float,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    url = f"http://127.0.0.1:{port}/healthz"
    while time.monotonic() < deadline:
        if game_process.poll() is not None:
            raise RuntimeError(f"Game container exited before healthz passed.\n{_tail(stderr_path)}")
        try:
            response = httpx.get(url, timeout=1.0)
            if response.status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    raise TimeoutError(f"Timed out waiting for {url}.\n{_tail(stderr_path)}")


def _wait_for_game_exit(
    game_process: subprocess.Popen[str],
    stderr_path: Path,
    *,
    timeout_seconds: float,
) -> None:
    try:
        return_code = game_process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(f"Timed out waiting for game container to exit.\n{_tail(stderr_path)}") from exc
    if return_code != 0:
        raise RuntimeError(f"Game container exited with status {return_code}.\n{_tail(stderr_path)}")


def _wait_for_player_exit(player_process: subprocess.Popen[str], stderr_path: Path) -> None:
    try:
        return_code = player_process.wait(timeout=10)
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(f"Timed out waiting for player container to exit.\n{_tail(stderr_path)}") from exc
    if return_code != 0:
        raise RuntimeError(f"Player container exited with status {return_code}.\n{_tail(stderr_path)}")


def _free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "packages" / "coworld").exists():
            return parent
    return Path.cwd()


def _new_workspace(prefix: str) -> Path:
    temp_root = _repo_root() / "tmp"
    temp_root.mkdir(exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=prefix, dir=temp_root))


def _tail(path: Path, limit: int = 4000) -> str:
    if not path.exists():
        return f"{path} does not exist"
    data = path.read_bytes()
    return data[-limit:].decode(errors="replace")
