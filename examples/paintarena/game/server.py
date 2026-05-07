from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse

CLIENTS_DIR = Path(__file__).parent / "clients"
REPLAY_MODE = "COGAME_LOAD_REPLAY_PATH" in os.environ
if REPLAY_MODE:
    REPLAY_DATA = json.loads(Path(os.environ["COGAME_LOAD_REPLAY_PATH"]).read_text())
    CONFIG = {"tokens": [], "width": 1, "height": 1, "max_ticks": 0, "tick_rate": 1.0}
    RESULTS_PATH = Path(os.environ["COGAME_LOAD_REPLAY_PATH"])
    REPLAY_PATH = Path(os.environ["COGAME_LOAD_REPLAY_PATH"])
else:
    REPLAY_DATA = {}
    CONFIG = json.loads(Path(os.environ["COGAME_CONFIG_PATH"]).read_text())
    RESULTS_PATH = Path(os.environ["COGAME_RESULTS_PATH"])
    REPLAY_PATH = Path(os.environ["COGAME_SAVE_REPLAY_PATH"])

TOKENS = CONFIG["tokens"]
WIDTH = CONFIG["width"]
HEIGHT = CONFIG["height"]
MAX_TICKS = CONFIG["max_ticks"]
TICK_RATE = CONFIG["tick_rate"]
DIRECTIONS = {
    "up": (0, -1),
    "down": (0, 1),
    "left": (-1, 0),
    "right": (1, 0),
    "stay": (0, 0),
}

app = FastAPI()
server: uvicorn.Server


class GameState:
    def __init__(self) -> None:
        self.players: dict[int, WebSocket] = {}
        self.positions = _starting_positions(len(TOKENS))
        self.tile_owners = [-1 for _ in range(WIDTH * HEIGHT)]
        self.scores = _scores(self.tile_owners)
        self.actions = ["stay" for _ in TOKENS]
        self.frames: list[dict[str, Any]] = []
        self.tick = 0
        self.started = False
        self.done = False
        self.paused = False
        self.tick_rate = float(TICK_RATE)


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
    await websocket.send_json(_snapshot())
    while not state.done:
        await asyncio.sleep(0.1)
        await websocket.send_json(_snapshot())


async def _drain_global_messages(websocket: WebSocket) -> None:
    async for _ in websocket.iter_json():
        pass


@app.websocket("/admin")
async def admin(websocket: WebSocket) -> None:
    await websocket.accept()
    await websocket.send_json(_snapshot())
    async for command in websocket.iter_json():
        if command["command"] == "pause":
            state.paused = True
        elif command["command"] == "resume":
            state.paused = False
        elif command["command"] == "tick_rate":
            state.tick_rate = float(command["tick_rate"])
        await websocket.send_json(_snapshot())


@app.websocket("/replay")
async def replay_viewer(websocket: WebSocket) -> None:
    await websocket.accept()
    await websocket.send_json({"type": "replay", **REPLAY_DATA})
    async for command in websocket.iter_json():
        await websocket.send_json({"type": "control", "command": command})


@app.websocket("/player")
async def player(websocket: WebSocket) -> None:
    slot = int(websocket.query_params["slot"])
    token = websocket.query_params["token"]
    if slot < 0 or slot >= len(TOKENS) or TOKENS[slot] != token:
        await websocket.close(code=1008)
        return

    await websocket.accept()
    state.players[slot] = websocket
    await websocket.send_json(_player_observation(slot))
    if len(state.players) == len(TOKENS) and not state.started:
        state.started = True
        asyncio.create_task(_play_game())

    async for message in websocket.iter_json():
        state.actions[slot] = _direction(message)


async def _play_game() -> None:
    await asyncio.sleep(0.5)
    while state.tick < MAX_TICKS:
        if state.paused:
            await asyncio.sleep(0.1)
            continue
        _step()
        snapshot = _snapshot()
        state.frames.append(snapshot)
        await _broadcast(snapshot)
        await asyncio.sleep(1.0 / state.tick_rate)

    results = _results()
    RESULTS_PATH.write_text(json.dumps(results))
    REPLAY_PATH.write_text(json.dumps({"config": CONFIG, "frames": state.frames, "results": results}))

    state.done = True
    for slot, websocket in state.players.items():
        await websocket.send_json({**_player_observation(slot), "type": "final", "done": True})
    await asyncio.sleep(0.5)
    server.should_exit = True


def _step() -> None:
    for slot, direction in enumerate(state.actions):
        dx, dy = DIRECTIONS[direction]
        x, y = state.positions[slot]
        state.positions[slot] = [min(max(x + dx, 0), WIDTH - 1), min(max(y + dy, 0), HEIGHT - 1)]

    for slot, (x, y) in enumerate(state.positions):
        state.tile_owners[y * WIDTH + x] = slot
    state.scores = _scores(state.tile_owners)
    state.tick += 1


async def _broadcast(snapshot: dict[str, Any] | None = None) -> None:
    for slot, websocket in state.players.items():
        await websocket.send_json(_player_observation(slot))


def _player_observation(slot: int) -> dict[str, Any]:
    return {**_snapshot(), "type": "observation", "slot": slot}


def _direction(message: dict[str, Any]) -> str:
    direction = str(message["move"])
    if direction not in DIRECTIONS:
        return "stay"
    return direction


def _results() -> dict[str, object]:
    return {
        "scores": [float(score) for score in state.scores],
        "painted_tiles": state.scores,
        "ticks": state.tick,
    }


def _snapshot() -> dict[str, Any]:
    return {
        "type": "state",
        "width": WIDTH,
        "height": HEIGHT,
        "positions": [position.copy() for position in state.positions],
        "tile_owners": state.tile_owners.copy(),
        "scores": state.scores.copy(),
        "tick": state.tick,
        "max_ticks": MAX_TICKS,
        "started": state.started,
        "paused": state.paused,
        "tick_rate": state.tick_rate,
        "done": state.done,
    }


def _starting_positions(count: int) -> list[list[int]]:
    corners = [[0, 0], [WIDTH - 1, HEIGHT - 1], [0, HEIGHT - 1], [WIDTH - 1, 0]]
    return [corners[slot % len(corners)].copy() for slot in range(count)]


def _scores(tile_owners: list[int]) -> list[int]:
    return [tile_owners.count(slot) for slot in range(len(TOKENS))]


state = GameState()


if __name__ == "__main__":
    server = uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=8080))
    server.run()
