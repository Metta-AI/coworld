from __future__ import annotations

import asyncio
import secrets
import socket
import subprocess
import tempfile
import time
from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, TypeAlias, cast
from urllib.parse import urlencode

import httpx
import websockets
from websockets.exceptions import InvalidHandshake, InvalidStatus

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PACKAGE_ROOT.parents[1]
CONTAINER_WORKDIR = "/coworld"
QueryParamValue: TypeAlias = str | int | float | bool


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


@dataclass(frozen=True)
class EpisodeRunSpec:
    cogame_image: str
    players: list[PlayerLaunchSpec]
    tokens: list[str]
    artifacts: EpisodeArtifacts
    timeout_seconds: float


@dataclass(frozen=True)
class PlayerLaunchSpec:
    image: str
    initial_params: Mapping[str, QueryParamValue] = field(default_factory=dict)

    @classmethod
    def from_episode_player(cls, player: Mapping[str, object]) -> PlayerLaunchSpec:
        initial_params: Mapping[str, QueryParamValue] = {}
        if "initial_params" in player:
            initial_params = cast(Mapping[str, QueryParamValue], player["initial_params"])
        return cls(image=cast(str, player["image"]), initial_params=initial_params)


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


def run_cogame_episode(spec: EpisodeRunSpec) -> None:
    port = _free_local_port()
    run_id = secrets.token_hex(8)
    game_container = f"coworld-cert-game-{run_id}"
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
                    "-e",
                    f"COGAME_CONFIG_PATH={CONTAINER_WORKDIR}/config.json",
                    "-e",
                    f"COGAME_RESULTS_PATH={CONTAINER_WORKDIR}/results.json",
                    "-e",
                    f"COGAME_SAVE_REPLAY_PATH={CONTAINER_WORKDIR}/replay.json",
                    "-v",
                    f"{spec.artifacts.workspace.resolve()}:{CONTAINER_WORKDIR}:rw",
                    spec.cogame_image,
                ],
                stdout=game_stdout,
                stderr=game_stderr,
                text=True,
            )

            _wait_for_health(port, game_process, spec.artifacts.game_stderr_path, timeout_seconds=spec.timeout_seconds)
            asyncio.run(_require_bad_player_rejected(f"ws://127.0.0.1:{port}/player?slot=0&token=bad"))

            for slot, player in enumerate(spec.players):
                container_name = f"coworld-cert-player-{run_id}-{slot}"
                engine_ws_url = _player_container_ws_url(port, slot, spec.tokens[slot], player)
                player_containers.append(container_name)
                player_stdout_path = spec.artifacts.logs_dir / f"player_{slot}.stdout.log"
                player_stderr_path = spec.artifacts.logs_dir / f"player_{slot}.stderr.log"
                player_stdout = stack.enter_context(player_stdout_path.open("w"))
                player_stderr = stack.enter_context(player_stderr_path.open("w"))
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
                                "-e",
                                f"COGAMES_ENGINE_WS_URL={engine_ws_url}",
                                player.image,
                            ],
                            stdout=player_stdout,
                            stderr=player_stderr,
                            text=True,
                        ),
                        player_stderr_path,
                    )
                )

            asyncio.run(_require_global_message(f"ws://127.0.0.1:{port}/global", timeout_seconds=spec.timeout_seconds))
            _wait_for_game_exit(game_process, spec.artifacts.game_stderr_path, timeout_seconds=spec.timeout_seconds)

            for player_process, player_stderr_path in player_processes:
                _wait_for_player_exit(player_process, player_stderr_path)
    finally:
        for container_name in player_containers:
            subprocess.run(["docker", "rm", "-f", container_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["docker", "rm", "-f", game_container], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _player_container_ws_url(port: int, slot: int, token: str, player: PlayerLaunchSpec) -> str:
    query: dict[str, QueryParamValue] = {"slot": slot, "token": token}
    query.update(player.initial_params)
    return f"ws://host.docker.internal:{port}/player?{urlencode(query)}"


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


def _new_workspace(prefix: str) -> Path:
    temp_root = REPO_ROOT / "tmp"
    temp_root.mkdir(exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=prefix, dir=temp_root))


def _tail(path: Path, limit: int = 4000) -> str:
    if not path.exists():
        return f"{path} does not exist"
    data = path.read_bytes()
    return data[-limit:].decode(errors="replace")
