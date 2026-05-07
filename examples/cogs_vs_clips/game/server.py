from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import uvicorn
from cogsguard.missions.machina_1 import make_cogsguard_mission, make_machina1_mission
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from mettagrid.config.mettagrid_config import MettaGridConfig
from mettagrid.policy.policy_env_interface import PolicyEnvInterface
from mettagrid.simulator import Simulator
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
        self.max_steps = config["max_steps"]
        self.seed = config["seed"]
        self.step_seconds = config["step_seconds"]
        self.results_path = results_path
        self.replay_path = replay_path
        self.request_shutdown = request_shutdown
        self.players: dict[int, WebSocket] = {}
        self.play_task: asyncio.Task[None] | None = None
        self.done = False
        self.paused = False
        self.start_deadline: float | None = None

        env = make_env(self.mission_name, num_agents=len(self.tokens), max_steps=self.max_steps, seed=self.seed)
        self.simulator = Simulator()
        self.sim = self.simulator.new_simulation(env, seed=self.seed)
        self.policy_env = PolicyEnvInterface.from_mg_cfg(self.sim.config)
        self.action_names = self.sim.action_names
        self.noop_action_index = self.action_names.index("noop")
        self.latest_action_indices = [self.noop_action_index] * len(self.tokens)
        (
            self.initial_replay,
            self.capacity_names,
            self.resource_to_capacity_id,
        ) = build_initial_replay(self.sim)
        self.replay_events: list[dict[str, Any]] = [self.global_baseline_message()]

    async def connect_player(self, slot: int, websocket: WebSocket) -> None:
        self.players[slot] = websocket
        if self.play_task is None:
            if len(self.players) == len(self.tokens):
                self.play_task = asyncio.create_task(self.play())
            elif self.start_deadline is None:
                self.start_deadline = asyncio.get_running_loop().time() + START_GRACE_SECONDS
                self.play_task = asyncio.create_task(self._play_after_grace())

    async def _play_after_grace(self) -> None:
        while len(self.players) < len(self.tokens):
            assert self.start_deadline is not None
            delay = self.start_deadline - asyncio.get_running_loop().time()
            if delay <= 0:
                break
            await asyncio.sleep(min(delay, 0.05))
        await self.play()

    def set_latest_action(self, slot: int, message: dict[str, Any]) -> None:
        if "action_index" in message:
            raw_action = message["action_index"]
        elif "action_name" in message:
            raw_action = message["action_name"]
        elif "action" in message:
            raw_action = message["action"]
        else:
            raw_action = self.noop_action_index

        if isinstance(raw_action, str):
            if raw_action in self.action_names:
                action_index = self.action_names.index(raw_action)
            else:
                action_index = self.noop_action_index
        else:
            action_index = int(raw_action)

        if action_index < 0 or action_index >= len(self.action_names):
            action_index = self.noop_action_index
        self.latest_action_indices[slot] = action_index

    def handle_global_message(self, message: dict[str, Any]) -> None:
        if message.get("type") == "action":
            agent_id = int(message["agent_id"])
            if 0 <= agent_id < len(self.tokens):
                self.set_latest_action(agent_id, message)
            return

        if message.get("type") != "control":
            return
        command = str(message.get("command", "")).lower()
        if command in {"play", "resume", "start"}:
            self.paused = False
        elif command in {"pause", "stop"}:
            self.paused = True
        elif command == "speed":
            speed = float(message["speed"])
            if speed > 0:
                self.step_seconds = 1.0 / speed
        elif command == "step":
            self.paused = False

    async def play(self) -> None:
        while self.sim.current_step < self.max_steps and not self.sim.is_done():
            if self.paused:
                await asyncio.sleep(0.05)
                continue
            await self._send_player_steps()
            await asyncio.sleep(self.step_seconds)
            self._apply_actions()
            self.sim.step()
            self.replay_events.append(self.global_delta_message())

        self.done = True
        results = self.results()
        self.results_path.write_text(json.dumps(results))
        if self.replay_path is not None:
            self.replay_path.write_text(json.dumps({"events": self.replay_events, "results": results}))
        await self._send_final()
        await asyncio.sleep(0.2)
        self.request_shutdown()

    async def _send_player_steps(self) -> None:
        await self._send_to_players({slot: self.player_message(slot) for slot in self.players})

    async def _send_final(self) -> None:
        final_message = {**self.snapshot(), "type": "final"}
        await self._send_to_players({slot: final_message for slot in self.players})

    async def _send_to_players(self, messages: dict[int, dict[str, Any]]) -> None:
        players = tuple(self.players.items())
        results = await asyncio.gather(
            *(websocket.send_json(messages[slot]) for slot, websocket in players), return_exceptions=True
        )
        for (slot, websocket), result in zip(players, results, strict=True):
            if isinstance(result, (RuntimeError, WebSocketDisconnect)):
                self.disconnect_player(slot, websocket)
            elif isinstance(result, Exception):
                raise result

    def disconnect_player(self, slot: int, websocket: WebSocket) -> None:
        if slot in self.players and self.players[slot] is websocket:
            del self.players[slot]

    def _apply_actions(self) -> None:
        for slot, action_index in enumerate(self.latest_action_indices):
            self.sim.agent(slot).set_action(self.action_names[action_index])

    def player_message(self, slot: int) -> dict[str, Any]:
        return {
            "type": "step",
            "mission": self.mission_name,
            "slot": slot,
            "step": self.sim.current_step,
            "observation": self.sim._c_sim.observations()[slot].tolist(),
            "action_names": self.action_names,
        }

    def player_config(self, slot: int) -> dict[str, Any]:
        return {
            "type": "player_config",
            "mission": self.mission_name,
            "slot": slot,
            "num_agents": len(self.tokens),
            "action_names": self.action_names,
            "observation_shape": list(self.policy_env.observation_shape),
            "observation": {
                "width": self.policy_env.obs_width,
                "height": self.policy_env.obs_height,
                "features": [
                    {"id": feature.id, "name": feature.name, "normalization": feature.normalization}
                    for feature in self.policy_env.obs_features
                ],
                "tags": self.policy_env.tags,
                "global_location": 254,
                "empty_location": 255,
            },
        }

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
                self.latest_action_indices,
                self.capacity_names,
                self.resource_to_capacity_id,
                ignored_object_types,
            ),
            "state": self.snapshot(),
        }

    def snapshot(self) -> dict[str, Any]:
        return {
            "type": "state",
            "mission": self.mission_name,
            "step": self.sim.current_step,
            "done": self.done,
            "paused": self.paused,
            "step_seconds": self.step_seconds,
            "scores": self.scores(),
            "num_agents": len(self.tokens),
            "connected_players": len(self.players),
            "action_names": self.action_names,
            "protocol": GLOBAL_PROTOCOL,
        }

    def global_status(self) -> dict[str, Any]:
        return {
            "mission": self.mission_name,
            "done": self.done,
            "scores": self.scores(),
            "num_agents": len(self.tokens),
            "connected_players": len(self.players),
            "action_names": self.action_names,
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
    env.game.map_builder.seed = seed
    return env


def noop_shutdown() -> None:
    pass


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

    @app.get("/global")
    def global_client() -> HTMLResponse:
        return HTMLResponse((CLIENTS_DIR / "global.html").read_text())

    @app.get("/admin")
    def admin_client() -> HTMLResponse:
        return HTMLResponse((CLIENTS_DIR / "admin.html").read_text())

    @app.get("/replay")
    def replay_client() -> HTMLResponse:
        return HTMLResponse((CLIENTS_DIR / "replay.html").read_text())

    @app.get("/player")
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
        while not game.done:
            await asyncio.sleep(game.step_seconds)
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
        await websocket.send_json(game.snapshot())
        async for command in websocket.iter_json():
            if command["command"] == "pause":
                game.paused = True
            elif command["command"] == "resume":
                game.paused = False
            elif command["command"] == "step_seconds":
                game.step_seconds = float(command["step_seconds"])
            await websocket.send_json(game.snapshot())

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
        await websocket.send_json(game.player_config(slot))
        await game.connect_player(slot, websocket)
        async for message in websocket.iter_json():
            if game.done:
                break
            game.set_latest_action(slot, message)
        game.disconnect_player(slot, websocket)

    return app


def create_replay_app(replay_data: dict[str, Any]) -> FastAPI:
    app = FastAPI()

    @app.get("/healthz")
    def healthz() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/replay")
    def replay_client() -> HTMLResponse:
        return HTMLResponse((CLIENTS_DIR / "replay.html").read_text())

    @app.websocket("/replay")
    async def replay_viewer(websocket: WebSocket) -> None:
        await websocket.accept()
        await websocket.send_json({"type": "replay", **replay_data})
        async for command in websocket.iter_json():
            await websocket.send_json({"type": "control", "command": command})

    return app


def load_app_from_env(request_shutdown: Callable[[], None] = noop_shutdown) -> FastAPI:
    if "COGAME_LOAD_REPLAY_PATH" in os.environ:
        replay_data = json.loads(Path(os.environ["COGAME_LOAD_REPLAY_PATH"]).read_text())
        return create_replay_app(replay_data)
    config = json.loads(Path(os.environ["COGAME_CONFIG_PATH"]).read_text())
    results_path = Path(os.environ["COGAME_RESULTS_PATH"])
    raw_replay_path = os.environ.get("COGAME_SAVE_REPLAY_PATH")
    replay_path = Path(raw_replay_path) if raw_replay_path else None
    return create_app(config, results_path=results_path, replay_path=replay_path, request_shutdown=request_shutdown)


def main() -> None:
    server: uvicorn.Server

    def request_shutdown() -> None:
        server.should_exit = True

    server = uvicorn.Server(uvicorn.Config(load_app_from_env(request_shutdown), host="0.0.0.0", port=8080))
    server.run()


if __name__ == "__main__":
    main()
