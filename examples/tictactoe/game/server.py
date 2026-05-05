from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse

CLIENTS_DIR = Path(__file__).parent / "clients"
CONFIG = json.loads(Path(os.environ["COGAME_CONFIG_PATH"]).read_text())
RESULTS_PATH = Path(os.environ["COGAME_RESULTS_PATH"])
REPLAY_PATH = Path(os.environ["COGAME_SAVE_REPLAY_PATH"])
TOKENS = CONFIG["tokens"]
MAX_TURNS = CONFIG["max_turns"]
WIN_LINES = [
    (0, 1, 2),
    (3, 4, 5),
    (6, 7, 8),
    (0, 3, 6),
    (1, 4, 7),
    (2, 5, 8),
    (0, 4, 8),
    (2, 4, 6),
]

app = FastAPI()
server: uvicorn.Server


class GameState:
    def __init__(self) -> None:
        self.board = [""] * 9
        self.players: dict[int, WebSocket] = {}
        self.moves: list[dict[str, int]] = []
        self.started = False
        self.done = False
        self.winner = -1


state = GameState()


@app.get("/healthz")
def healthz() -> dict[str, bool]:
    return {"ok": True}


@app.get("/global")
def global_client() -> HTMLResponse:
    return HTMLResponse((CLIENTS_DIR / "global.html").read_text())


@app.get("/replay")
def replay_client() -> HTMLResponse:
    return HTMLResponse((CLIENTS_DIR / "replay.html").read_text())


@app.get("/player")
def player_client() -> HTMLResponse:
    return HTMLResponse((CLIENTS_DIR / "player.html").read_text())


@app.websocket("/global")
async def global_viewer(websocket: WebSocket) -> None:
    await websocket.accept()
    await websocket.send_json(_snapshot())
    while not state.done:
        await asyncio.sleep(0.05)


@app.websocket("/player")
async def player(websocket: WebSocket) -> None:
    slot = int(websocket.query_params["slot"])
    token = websocket.query_params["token"]
    if slot < 0 or slot >= len(TOKENS) or TOKENS[slot] != token:
        await websocket.close(code=1008)
        return

    await websocket.accept()
    state.players[slot] = websocket
    if len(state.players) == len(TOKENS) and not state.started:
        state.started = True
        asyncio.create_task(_play_game())

    while not state.done:
        await asyncio.sleep(0.05)


async def _play_game() -> None:
    await asyncio.sleep(0.5)
    for turn in range(MAX_TURNS):
        slot = turn % len(TOKENS)
        mark = "X" if slot == 0 else "O"
        websocket = state.players[slot]
        await websocket.send_json({"type": "turn", "slot": slot, "board": state.board})
        message = await websocket.receive_json()
        move = int(message["move"])
        if move < 0 or move >= len(state.board) or state.board[move]:
            move = state.board.index("")
        state.board[move] = mark
        state.moves.append({"slot": slot, "move": move})

        winner = _winner()
        if winner >= 0:
            state.winner = winner
            break
        if "" not in state.board:
            break

    results = _results()
    RESULTS_PATH.write_text(json.dumps(results))
    REPLAY_PATH.write_text(json.dumps({"board": state.board, "moves": state.moves, "results": results}))

    final_snapshot = {**_snapshot(), "done": True}
    for websocket in state.players.values():
        await websocket.send_json({"type": "final", **final_snapshot})
    state.done = True
    await asyncio.sleep(0.5)
    server.should_exit = True


def _winner() -> int:
    for a, b, c in WIN_LINES:
        if state.board[a] and state.board[a] == state.board[b] == state.board[c]:
            return 0 if state.board[a] == "X" else 1
    return -1


def _results() -> dict[str, object]:
    if state.winner == 0:
        scores = [1.0, 0.0]
    elif state.winner == 1:
        scores = [0.0, 1.0]
    else:
        scores = [0.5, 0.5]
    return {"scores": scores, "winner": state.winner, "moves": len(state.moves)}


def _snapshot() -> dict[str, object]:
    return {
        "type": "state",
        "board": state.board,
        "moves": state.moves,
        "winner": state.winner,
        "done": state.done,
    }


if __name__ == "__main__":
    server = uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=8080))
    server.run()
