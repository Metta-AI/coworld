from __future__ import annotations

import asyncio
import gzip
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast
from urllib.parse import unquote, urlencode, urlparse

import numpy as np
import uvicorn
from cogsguard.missions.machina_1 import make_cogsguard_mission, make_machina1_mission
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from coworld.runner.io import read_data
from mettagrid.config.mettagrid_config import MettaGridConfig
from mettagrid.map_builder.map_builder import HasSeed
from mettagrid.runner.live_episode import LiveMettaGridEpisode, TickMode
from mettagrid.util.grid_object_formatter import format_grid_object

CLIENTS_DIR = Path(__file__).parent / "clients"
METTASCOPE_DIST_DIR = Path(os.environ.get("METTASCOPE_DIST_DIR", Path(__file__).parent / "mettascope"))
GLOBAL_PROTOCOL = "mettagrid.mettascope.live.v1"
START_GRACE_SECONDS = 0.5


def build_initial_replay(sim) -> tuple[dict[str, Any], list[str], dict[int, int]]:
    game_config = sim.config.game
    game_config_dict = game_config.model_dump(mode="json", exclude_none=True)
    agent_inv_limits = game_config.agents[0].inventory.limits if game_config.agents else {}
    capacity_names = sorted(agent_inv_limits.keys())
    resource_to_capacity_id = {}
    for capacity_id, capacity_name in enumerate(capacity_names):
        for resource_name in agent_inv_limits[capacity_name].resources:
            resource_to_capacity_id[sim.resource_names.index(resource_name)] = capacity_id
    id_map = game_config.id_map()
    tags = {name: idx for idx, name in enumerate(id_map.tag_names())}
    return (
        {
            "version": 2,
            "action_names": list(sim.action_ids.keys()),
            "item_names": sim.resource_names,
            "type_names": sim.object_type_names,
            "capacity_names": capacity_names,
            "tags": tags,
            "map_size": [sim.map_width, sim.map_height],
            "num_agents": sim.num_agents,
            "max_steps": 0,
            "mg_config": {"label": "Cogs vs Clips Live", "game": game_config_dict},
            "objects": [],
        },
        capacity_names,
        resource_to_capacity_id,
    )


def build_step_replay(
    sim,
    action_indices: list[int],
    capacity_names: list[str],
    resource_to_capacity_id: dict[int, int],
    ignored_object_types: list[str] | None = None,
) -> dict[str, Any]:
    actions = np.asarray(action_indices, dtype=np.int32)
    rewards = np.zeros(sim.num_agents)
    objects = []
    for grid_object in sim.grid_objects(ignore_types=ignored_object_types or []).values():
        formatted = format_grid_object(
            grid_object,
            actions,
            sim.action_success,
            rewards,
            sim.episode_rewards,
        )
        raw_capacities = formatted.pop("inventory_capacities_raw", {})
        group_capacities = {}
        for resource_id, effective_limit in raw_capacities.items():
            capacity_id = resource_to_capacity_id.get(resource_id)
            if capacity_id is not None and capacity_id not in group_capacities:
                group_capacities[capacity_id] = effective_limit
        formatted["inventory_capacities"] = sorted(group_capacities.items())
        objects.append(formatted)
    return {
        "step": sim.current_step,
        "objects": objects,
        "episode_stats": sim._c_sim.get_episode_stats(),
        "capacity_names": capacity_names,
    }


class CogsVsClipsGame:
    def __init__(
        self,
        config: dict[str, Any],
        results_path: Path,
        replay_path: Path | None,
        request_shutdown: Callable[[], None],
    ):
        self.mission_name = config["mission"]
        self.tokens = config["tokens"]
        max_steps = config["max_steps"]
        seed = config["seed"]

        env = make_env(self.mission_name, num_agents=len(self.tokens), max_steps=max_steps, seed=seed)
        self.episode = LiveMettaGridEpisode.from_env(
            env,
            seed=seed,
            tokens=self.tokens,
            max_steps=max_steps,
            step_seconds=config["step_seconds"],
            message_context={"mission": self.mission_name},
            start_grace_seconds=START_GRACE_SECONDS,
            disconnect_exception_types=(RuntimeError, WebSocketDisconnect),
            request_shutdown=request_shutdown,
        )
        self.episode.configure_artifacts(
            results_path=results_path,
            replay_path=replay_path,
            results_builder=self.results,
        )
        self.sim = self.episode.sim
        (
            self.initial_replay,
            self.capacity_names,
            self.resource_to_capacity_id,
        ) = build_initial_replay(self.sim)
        self.episode.configure_replay_events(
            baseline_builder=self.global_baseline_message,
            step_builder=self.global_delta_message,
        )

    def handle_global_message(self, message: dict[str, Any]) -> None:
        message_type = message["type"]
        if message_type == "action":
            agent_id = int(message["agent_id"])
            if 0 <= agent_id < len(self.tokens):
                self.episode.set_policy_action(agent_id, message, connection_id="global")
            return
        if message_type != "control":
            return
        command = str(message["command"]).lower()
        if command in {"play", "resume", "start"}:
            self.episode.paused = False
        elif command in {"pause", "stop"}:
            self.episode.paused = True
        elif command == "speed":
            speed = float(message["speed"])
            if speed > 0:
                self.episode.step_seconds = 1.0 / speed
        elif command == "step":
            self.episode.paused = False

    def global_assign_message(self) -> dict[str, Any]:
        return {
            "type": "assign",
            "protocol": GLOBAL_PROTOCOL,
            "agent_id": -1,
            "initial_replay": self.initial_replay,
            "status": self.global_status(),
        }

    def global_hello_message(self) -> dict[str, Any]:
        return {
            "type": "hello",
            "protocol": GLOBAL_PROTOCOL,
            "status": self.global_status(),
        }

    def global_baseline_message(self) -> dict[str, Any]:
        return self._global_step_message()

    def global_delta_message(self) -> dict[str, Any]:
        return self._global_step_message(ignored_object_types=["wall"])

    def _global_step_message(self, *, ignored_object_types: list[str] | None = None) -> dict[str, Any]:
        return {
            "type": "step",
            "protocol": GLOBAL_PROTOCOL,
            **build_step_replay(
                self.sim,
                self.episode.latest_action_indices,
                self.capacity_names,
                self.resource_to_capacity_id,
                ignored_object_types,
            ),
            "state": self.snapshot(),
        }

    def snapshot(self) -> dict[str, Any]:
        return {**self.episode.snapshot(), "global_protocol": GLOBAL_PROTOCOL}

    def admin_snapshot(self) -> dict[str, Any]:
        snapshot = self.snapshot()
        snapshot["slots"] = [
            {
                **slot_state,
                "takeover_url": self.takeover_url(int(slot_state["slot"])),
            }
            for slot_state in snapshot["slots"]
        ]
        return snapshot

    def takeover_url(self, slot: int) -> str:
        return f"/clients/player?{urlencode({'slot': slot, 'token': self.tokens[slot], 'takeover': 1})}"

    def global_status(self) -> dict[str, Any]:
        return {
            "mission": self.mission_name,
            "done": self.episode.done,
            "scores": self.scores(),
            "num_agents": len(self.tokens),
            "connected_players": len(self.episode.connections),
            "action_names": self.episode.action_names,
            "protocol": GLOBAL_PROTOCOL,
        }

    def scores(self) -> list[float]:
        return [float(score) for score in self.sim.episode_rewards.tolist()]

    def results(self) -> dict[str, Any]:
        return {"scores": self.scores(), "steps": self.sim.current_step, "mission": self.mission_name}


def make_env(mission_name: str, *, num_agents: int, max_steps: int, seed: int) -> MettaGridConfig:
    if mission_name == "machina_1":
        mission = make_machina1_mission(num_agents=num_agents, max_steps=max_steps)
    elif mission_name == "cogsguard":
        mission = make_cogsguard_mission(num_agents=num_agents, max_steps=max_steps)
    else:
        raise ValueError(f"Unknown mission: {mission_name}")
    env = mission.make_env()
    map_builder = env.game.map_builder
    if not isinstance(map_builder, HasSeed):
        raise TypeError(f"{mission_name} map builder must support seeding")
    map_builder.seed = seed
    return env


def noop_shutdown() -> None:
    pass


def _file_uri_path(uri: str) -> Path:
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        raise ValueError(f"cogs_vs_clips artifacts must use file:// URIs: {uri}")
    return Path(unquote(parsed.path))


def create_app(
    config: dict[str, Any],
    results_path: Path,
    replay_path: Path | None,
    request_shutdown: Callable[[], None] = noop_shutdown,
) -> FastAPI:
    game = CogsVsClipsGame(
        config,
        results_path=results_path,
        replay_path=replay_path,
        request_shutdown=request_shutdown,
    )
    app = FastAPI()
    if METTASCOPE_DIST_DIR.is_dir():
        app.mount("/mettascope", StaticFiles(directory=METTASCOPE_DIST_DIR), name="mettascope")

    @app.get("/healthz")
    def healthz() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/clients/global")
    def global_client() -> HTMLResponse:
        return HTMLResponse((CLIENTS_DIR / "global.html").read_text())

    @app.get("/clients/admin")
    def admin_client() -> HTMLResponse:
        return HTMLResponse((CLIENTS_DIR / "admin.html").read_text())

    @app.get("/clients/replay")
    def replay_client() -> HTMLResponse:
        return HTMLResponse((CLIENTS_DIR / "replay.html").read_text())

    @app.get("/clients/player")
    def player_client() -> HTMLResponse:
        return HTMLResponse((CLIENTS_DIR / "player.html").read_text())

    @app.websocket("/global")
    async def global_viewer(websocket: WebSocket) -> None:
        await websocket.accept()
        sender = asyncio.create_task(_send_global_snapshots(websocket))
        receiver = asyncio.create_task(_drain_global_messages(websocket))
        done, pending = await asyncio.wait({sender, receiver}, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            task.result()

    async def _send_global_snapshots(websocket: WebSocket) -> None:
        await websocket.send_json(game.global_hello_message())
        await websocket.send_json(game.global_assign_message())
        await websocket.send_json(game.global_baseline_message())
        while not game.episode.done:
            await asyncio.sleep(game.episode.step_seconds)
            await websocket.send_json(game.global_delta_message())
        await websocket.send_json(
            {
                "type": "done",
                "protocol": GLOBAL_PROTOCOL,
                "steps": game.sim.current_step,
                "status": game.global_status(),
            }
        )

    async def _drain_global_messages(websocket: WebSocket) -> None:
        async for message in websocket.iter_json():
            game.handle_global_message(message)

    @app.websocket("/admin")
    async def admin(websocket: WebSocket) -> None:
        await websocket.accept()
        send_lock = asyncio.Lock()
        sender = asyncio.create_task(_send_admin_snapshots(websocket, send_lock))
        receiver = asyncio.create_task(_drain_admin_commands(websocket, send_lock))
        done, pending = await asyncio.wait({sender, receiver}, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            task.result()

    async def _send_admin_snapshots(websocket: WebSocket, send_lock: asyncio.Lock) -> None:
        while not game.episode.done:
            await _send_admin_snapshot(websocket, send_lock)
            await asyncio.sleep(0.25)
        await _send_admin_snapshot(websocket, send_lock)

    async def _drain_admin_commands(websocket: WebSocket, send_lock: asyncio.Lock) -> None:
        async for command in websocket.iter_json():
            if command["command"] == "pause":
                game.episode.paused = True
            elif command["command"] == "resume":
                game.episode.paused = False
            elif command["command"] == "step_seconds":
                game.episode.step_seconds = float(command["step_seconds"])
            elif command["command"] == "tick_mode":
                tick_mode = command["tick_mode"]
                if tick_mode not in {"fixed", "tick_when_act"}:
                    raise ValueError(f"Unknown tick_mode: {tick_mode}")
                game.episode.tick_mode = cast(TickMode, tick_mode)
            elif command["command"] == "human_action_timeout_seconds":
                game.episode.human_action_timeout_seconds = float(command["human_action_timeout_seconds"])
            elif command["command"] == "boot_connection":
                await game.episode.boot_connection(str(command["connection_id"]))
            await _send_admin_snapshot(websocket, send_lock)

    async def _send_admin_snapshot(websocket: WebSocket, send_lock: asyncio.Lock) -> None:
        async with send_lock:
            await websocket.send_json(game.admin_snapshot())

    @app.websocket("/player")
    async def player(websocket: WebSocket) -> None:
        if "slot" not in websocket.query_params or "token" not in websocket.query_params:
            await websocket.close(code=1008)
            return

        slot = int(websocket.query_params["slot"])
        token = websocket.query_params["token"]
        if slot < 0 or slot >= len(game.tokens) or game.tokens[slot] != token:
            await websocket.close(code=1008)
            return

        await websocket.accept()
        connection_id = await game.episode.connect_player(slot, websocket)
        async for message in websocket.iter_json():
            if game.episode.done:
                break
            await game.episode.handle_player_message(connection_id, message)
        game.episode.disconnect_player(connection_id)

    return app


def load_replay_data(replay_uri: str) -> dict[str, Any]:
    replay_data = read_data(replay_uri)
    if replay_uri.endswith((".json.z", ".json.gz")):
        replay_data = gzip.decompress(replay_data)
    return json.loads(replay_data)


def create_replay_app() -> FastAPI:
    app = FastAPI()

    @app.get("/healthz")
    def healthz() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/clients/replay")
    def replay_client() -> HTMLResponse:
        return HTMLResponse((CLIENTS_DIR / "replay.html").read_text())

    @app.websocket("/replay")
    async def replay_viewer(websocket: WebSocket) -> None:
        if "uri" not in websocket.query_params:
            await websocket.close(code=1008)
            return
        await websocket.accept()
        await websocket.send_json({"type": "replay", **load_replay_data(websocket.query_params["uri"])})
        async for command in websocket.iter_json():
            await websocket.send_json({"type": "control", "command": command})

    return app


def load_app_from_env(request_shutdown: Callable[[], None] = noop_shutdown) -> FastAPI:
    if os.environ.get("COGAME_REPLAY_SERVER") == "1":
        return create_replay_app()
    config = json.loads(read_data(os.environ["COGAME_CONFIG_URI"]))
    results_path = _file_uri_path(os.environ["COGAME_RESULTS_URI"])
    raw_replay_uri = os.environ.get("COGAME_SAVE_REPLAY_URI")
    replay_path = _file_uri_path(raw_replay_uri) if raw_replay_uri else None
    return create_app(config, results_path=results_path, replay_path=replay_path, request_shutdown=request_shutdown)


def main() -> None:
    server: uvicorn.Server

    def request_shutdown() -> None:
        server.should_exit = True

    server = uvicorn.Server(uvicorn.Config(load_app_from_env(request_shutdown), host="0.0.0.0", port=8080))
    server.run()


if __name__ == "__main__":
    main()
