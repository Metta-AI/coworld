from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import socket
import subprocess
import tempfile
import time
import zlib
from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping
from urllib.parse import urlencode

import httpx
import websockets
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
from websockets.exceptions import ConnectionClosed, InvalidHandshake, InvalidStatus

from coworld.reporter_protocol import ReporterEpisodeInput, ReportRequest
from coworld.schema_validation import validate_json_schema
from coworld.types import CoworldEpisodeJobSpec, CoworldRunnableSpec

CONTAINER_WORKDIR = "/coworld"
CONFIG_ENV_VAR = "COGAME_CONFIG_URI"
RESULTS_ENV_VAR = "COGAME_RESULTS_URI"
REPLAY_SAVE_ENV_VAR = "COGAME_SAVE_REPLAY_URI"
REPLAY_LOAD_ENV_VAR = "COGAME_LOAD_REPLAY_URI"
GAME_HOST_ENV_VAR = "COGAME_HOST"
GAME_PORT_ENV_VAR = "COGAME_PORT"
REPORT_REQUEST_ENV_VAR = "COGAME_REPORT_REQUEST"
GAME_HOST = "0.0.0.0"
GAME_PORT = 8080
LOCAL_DOCKER_NETWORK = "coworld-local"
LOCAL_GAME_NETWORK_ALIAS_PREFIX = "coworld-game-"
LOCAL_EPISODE_CONTAINER_PREFIX = "coworld-cert"

# Hosted Coworld manifests store images as backend container-image ids: the "img_" prefix followed by a
# UUID (see ContainerImageId / PrefixedId in metta-app-backend-client). The backend substitutes a pullable
# URI when serving a manifest, but only once the image has been mirrored to the public registry; until then
# it leaves the raw id in place. Such an id is not a Docker reference, so guard against it reaching `docker`
# and surface the real cause. Match the full id shape so legitimate local tags like "img_game:latest" run.
_CONTAINER_IMAGE_ID_RE = re.compile(r"^img_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class DockerImageInspectEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    os_name: str = Field(alias="Os")
    architecture: str = Field(alias="Architecture")


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
            replay_path=workspace / "replay",
            logs_dir=logs_dir,
            game_stdout_path=logs_dir / "game.stdout.log",
            game_stderr_path=logs_dir / "game.stderr.log",
        )

    def policy_log_path(self, slot: int) -> Path:
        return self.logs_dir / f"policy_agent_{slot}.log"

    def policy_artifact_path(self, slot: int) -> Path:
        """Per-player artifact (single .zip) the player uploads at episode end.

        Lives in the workspace root (not logs/) since it is a separate artifact from logs.
        """
        return self.workspace / f"policy_artifact_{slot}.zip"


@dataclass(frozen=True)
class EpisodeRunSpec:
    game: RunnableLaunchSpec
    players: list[PlayerLaunchSpec]
    tokens: list[str]
    artifacts: EpisodeArtifacts
    timeout_seconds: float
    container_prefix: str = LOCAL_EPISODE_CONTAINER_PREFIX
    secret_env: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class RunnableLaunchSpec:
    image: str
    run: tuple[str, ...] = ()
    env: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def from_model(cls, runnable: CoworldRunnableSpec) -> RunnableLaunchSpec:
        return cls(image=runnable.image, run=tuple(runnable.run), env=runnable.env)


@dataclass(frozen=True)
class PlayerLaunchSpec(RunnableLaunchSpec):
    @classmethod
    def from_model(cls, player: CoworldRunnableSpec) -> PlayerLaunchSpec:
        runnable = RunnableLaunchSpec.from_model(player)
        return cls(
            image=runnable.image,
            run=runnable.run,
            env=runnable.env,
        )


def assert_docker_image_reachable(image: str, *, label: str = "Docker image") -> None:
    if _CONTAINER_IMAGE_ID_RE.match(image):
        raise RuntimeError(
            f"{label} is an unresolved Coworld image id: {image}\n"
            "The backend has not published this image to the public registry yet, so it cannot be pulled "
            "locally. Re-download the Coworld after it finishes publishing (`coworld download <coworld> "
            "--refresh`), or wait and retry; if it never resolves, the Coworld's image may not be available "
            "for local runs."
        )

    local_result = subprocess.run(["docker", "image", "inspect", image], capture_output=True, text=True, timeout=30)
    if local_result.returncode == 0:
        _assert_linux_amd64_image(image, label=label, inspect_stdout=local_result.stdout)
        return

    remote_result = subprocess.run(["docker", "manifest", "inspect", image], capture_output=True, text=True, timeout=60)
    if remote_result.returncode == 0:
        return

    raise RuntimeError(
        f"{label} is not available locally or reachable remotely: {image}\n"
        f"docker image inspect stderr:\n{local_result.stderr[-2000:]}\n"
        f"docker manifest inspect stderr:\n{remote_result.stderr[-2000:]}"
    )


def _assert_linux_amd64_image(image: str, *, label: str, inspect_stdout: str) -> None:
    entries = TypeAdapter(list[DockerImageInspectEntry]).validate_json(inspect_stdout)
    if len(entries) != 1:
        raise RuntimeError(f"docker image inspect returned {len(entries)} entries for {image}")
    entry = entries[0]
    if entry.os_name != "linux" or entry.architecture != "amd64":
        raise RuntimeError(
            f"{label} {image} is {entry.os_name}/{entry.architecture}; "
            "Coworld episodes require linux/amd64 images. "
            "Rebuild the image with: docker build --platform linux/amd64 ..."
        )


def assert_episode_images_reachable(job: CoworldEpisodeJobSpec) -> None:
    assert_docker_image_reachable(job.game_runnable.image, label="game.runnable.image")
    for slot, player in enumerate(job.players):
        assert_docker_image_reachable(player.image, label=f"players[{slot}].image")


def run_coworld_episode(
    job: CoworldEpisodeJobSpec,
    artifacts: EpisodeArtifacts,
    *,
    timeout_seconds: float,
    verify_replay: bool = False,
    container_prefix: str = LOCAL_EPISODE_CONTAINER_PREFIX,
    secret_env: Mapping[str, str] | None = None,
) -> None:
    assert_episode_images_reachable(job)
    tokens = generate_tokens(len(job.players))
    write_coworld_game_config(job, artifacts, tokens)

    run_spec = EpisodeRunSpec(
        game=RunnableLaunchSpec.from_model(job.game_runnable),
        players=[PlayerLaunchSpec.from_model(player) for player in job.players],
        tokens=tokens,
        artifacts=artifacts,
        timeout_seconds=timeout_seconds,
        container_prefix=container_prefix,
        secret_env=secret_env or {},
    )
    run_episode_containers(run_spec, verify_replay=verify_replay)

    results = json.loads(artifacts.results_path.read_text(encoding="utf-8"))
    validate_json_schema(results, job.results_schema)


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


def replay_session_path() -> str:
    return "/replay"


def replay_client_url(port: int) -> str:
    return f"http://127.0.0.1:{port}/client/replay"


def ensure_local_docker_network() -> None:
    inspect_command = ["docker", "network", "inspect", LOCAL_DOCKER_NETWORK]
    inspect_result = subprocess.run(
        inspect_command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if inspect_result.returncode == 0:
        return

    create_result = subprocess.run(
        ["docker", "network", "create", LOCAL_DOCKER_NETWORK],
        capture_output=True,
        text=True,
    )
    if create_result.returncode == 0:
        return

    if (
        subprocess.run(
            inspect_command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode
        != 0
    ):
        raise RuntimeError(f"Failed to create Docker network {LOCAL_DOCKER_NETWORK}.\n{create_result.stderr[-2000:]}")


def run_episode_containers(spec: EpisodeRunSpec, *, verify_replay: bool = True) -> None:
    port = _free_local_port()
    run_id = secrets.token_hex(8)
    game_network_alias = f"{LOCAL_GAME_NETWORK_ALIAS_PREFIX}{run_id}"
    game_container = f"{spec.container_prefix}-game-{run_id}"
    replay_container = f"{spec.container_prefix}-replay-{run_id}"
    player_containers: list[str] = []
    player_processes: list[tuple[subprocess.Popen[str], Path]] = []

    ensure_local_docker_network()
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
                    "--network",
                    LOCAL_DOCKER_NETWORK,
                    "--network-alias",
                    game_network_alias,
                    "-p",
                    f"127.0.0.1:{port}:{GAME_PORT}",
                    *_env_args(spec.game.env),
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
                    "-v",
                    f"{spec.artifacts.workspace.resolve()}:{CONTAINER_WORKDIR}:rw",
                    *_image_command(spec.game),
                ],
                stdout=game_stdout,
                stderr=game_stderr,
                text=True,
            )

            _wait_for_health(port, game_process, spec.artifacts.game_stderr_path, timeout_seconds=spec.timeout_seconds)
            if spec.players:
                _require_http_ok(_player_client_url(port, 0, spec.tokens[0]))
                asyncio.run(_require_bad_player_rejected(f"ws://127.0.0.1:{port}/player?slot=0&token=bad"))
            _require_http_ok(f"http://127.0.0.1:{port}/client/global")

            secret_env_key_args = [arg for key in spec.secret_env for arg in ("-e", key)]
            player_subprocess_env = {**os.environ, **spec.secret_env} if spec.secret_env else None

            for slot, player in enumerate(spec.players):
                container_name = f"{spec.container_prefix}-player-{run_id}-{slot}"
                engine_ws_url = _player_container_ws_url(game_network_alias, slot, spec.tokens[slot])
                player_containers.append(container_name)
                player_log_path = spec.artifacts.policy_log_path(slot)
                player_log = stack.enter_context(player_log_path.open("w"))
                # Local parity for the hosted per-player artifact upload: mount the workspace into the
                # player container and hand it a file:// URL for its per-slot artifact .zip. io.write_data
                # creates parent dirs, so the player writes straight to the workspace and the runner
                # finds it at policy_artifact_path(slot). No upload server needed locally.
                artifact_filename = spec.artifacts.policy_artifact_path(slot).name
                artifact_mount = f"{spec.artifacts.workspace}:/coworld-artifact:rw"
                artifact_upload_url = f"file:///coworld-artifact/{artifact_filename}"
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
                                "-v",
                                artifact_mount,
                                *_env_args(player.env),
                                *secret_env_key_args,
                                "-e",
                                f"COWORLD_PLAYER_WS_URL={engine_ws_url}",
                                "-e",
                                f"COGAMES_ENGINE_WS_URL={engine_ws_url}",
                                "-e",
                                f"COWORLD_PLAYER_ARTIFACT_UPLOAD_URL={artifact_upload_url}",
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

            asyncio.run(_require_global_message(f"ws://127.0.0.1:{port}/global", timeout_seconds=spec.timeout_seconds))
            _wait_for_game_exit(game_process, spec.artifacts.game_stderr_path, timeout_seconds=spec.timeout_seconds)

            for player_process, player_stderr_path in player_processes:
                _wait_for_player_exit(player_process, player_stderr_path)

            if not verify_replay:
                return

            replay_port = _free_local_port()
            replay_load_dir = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="coworld-replay-load-")))
            replay_load_path = replay_load_dir / "replay.z"
            replay_load_path.write_bytes(zlib.compress(spec.artifacts.replay_path.read_bytes()))
            replay_uri = "file:///coworld-replay/replay.z"
            replay_process = subprocess.Popen(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--name",
                    replay_container,
                    "-p",
                    f"127.0.0.1:{replay_port}:{GAME_PORT}",
                    *_env_args(spec.game.env),
                    "-e",
                    f"{GAME_HOST_ENV_VAR}={GAME_HOST}",
                    "-e",
                    f"{GAME_PORT_ENV_VAR}={GAME_PORT}",
                    "-e",
                    f"{REPLAY_LOAD_ENV_VAR}={replay_uri}",
                    "-v",
                    f"{replay_load_dir}:/coworld-replay:ro",
                    *_image_command(spec.game),
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
            _require_http_ok(replay_client_url(replay_port), allow_redirect=True)
            asyncio.run(
                _require_replay_message(
                    f"ws://127.0.0.1:{replay_port}{replay_session_path()}",
                    timeout_seconds=spec.timeout_seconds,
                )
            )
    finally:
        for container_name in player_containers:
            subprocess.run(["docker", "rm", "-f", container_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["docker", "rm", "-f", game_container], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["docker", "rm", "-f", replay_container], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def run_reporter(
    reporter: RunnableLaunchSpec,
    *,
    workspace: Path,
    request_id: str,
    episodes: list[ReporterEpisodeInput],
    timeout_seconds: float,
    container_prefix: str = LOCAL_EPISODE_CONTAINER_PREFIX,
) -> bytes:
    """Run one reporter container against direct episode inputs and return its report zip.

    Mounts ``workspace`` into the container, passes ``COGAME_REPORT_REQUEST``
    with container-visible ``file://`` artifact refs, runs the reporter to
    completion, and returns the bytes it wrote. A reporter is a short-lived
    process-style container that only does file I/O, so it needs neither the
    local network nor a published port.
    """
    workspace.mkdir(parents=True, exist_ok=True)
    report_path = workspace / "report.zip"
    report_path.unlink(missing_ok=True)
    report_request = ReportRequest(
        request_id=request_id,
        episodes=episodes,
        report_uri=f"file://{CONTAINER_WORKDIR}/report.zip",
    )

    container_name = f"{container_prefix}-reporter-{secrets.token_hex(8)}"
    completed = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--name",
            container_name,
            *_env_args(reporter.env),
            "-e",
            f"{REPORT_REQUEST_ENV_VAR}={report_request.model_dump_json(exclude_none=True)}",
            "-v",
            f"{workspace.resolve()}:{CONTAINER_WORKDIR}:rw",
            *_image_command(reporter),
        ],
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"Reporter container exited with status {completed.returncode}.\n{completed.stderr[-4000:]}")
    if not report_path.exists():
        raise FileNotFoundError(f"Reporter container did not write a report to report_uri.\n{completed.stderr[-4000:]}")
    return report_path.read_bytes()


def _player_container_ws_url(host: str, slot: int, token: str) -> str:
    return f"ws://{host}:{GAME_PORT}/player?{_player_query(slot, token)}"


def _player_client_url(port: int, slot: int, token: str) -> str:
    return f"http://127.0.0.1:{port}/client/player?{_player_query(slot, token)}"


def _player_query(slot: int, token: str) -> str:
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
        async with websockets.connect(url, open_timeout=5) as websocket:
            try:
                await asyncio.wait_for(websocket.recv(), timeout=2.0)
            except ConnectionClosed:
                rejected = True
            except asyncio.TimeoutError:
                pass
    except InvalidStatus as exc:
        rejected = exc.response.status_code in {401, 403}
        if not rejected:
            raise
    except (ConnectionClosed, InvalidHandshake):
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
        return_code = player_process.wait(timeout=30)
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
