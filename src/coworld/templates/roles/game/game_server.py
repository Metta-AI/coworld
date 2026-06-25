from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

import uvicorn
from fastapi import FastAPI, Response, WebSocket
from pydantic import BaseModel, Field

HTTP_USER_AGENT = "coworld-game-template/0.1"


class GameConfig(BaseModel):
    tokens: list[str] = Field(min_length=1)
    max_ticks: int = Field(default=1, gt=0)


def read_data(uri: str) -> bytes:
    parsed = urlparse(uri)
    if parsed.scheme in ("http", "https"):
        request = Request(uri, headers={"User-Agent": HTTP_USER_AGENT})
        with urlopen(request, timeout=30) as response:
            return response.read()
    if parsed.scheme == "file":
        return Path(unquote(parsed.path)).read_bytes()
    if parsed.scheme == "":
        return Path(uri).read_bytes()
    raise ValueError(f"Unsupported URI for read_data: {uri}")


def write_data(uri: str, data: bytes, content_type: str) -> None:
    parsed = urlparse(uri)
    if parsed.scheme in ("http", "https"):
        request = Request(uri, data=data, method="PUT")
        request.add_header("Content-Type", content_type)
        request.add_header("User-Agent", HTTP_USER_AGENT)
        with urlopen(request, timeout=60):
            return
    if parsed.scheme == "file":
        path = Path(unquote(parsed.path))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return
    if parsed.scheme == "":
        path = Path(uri)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return
    raise ValueError(f"Unsupported URI for write_data: {uri}")


app = FastAPI()


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/client/player")
def player_client(slot: int, token: str) -> Response:
    html = f"<html><body><h1>Player {slot}</h1><p>token={token}</p></body></html>"
    return Response(html, media_type="text/html")


@app.get("/client/global")
def global_client() -> Response:
    return Response("<html><body><h1>Coworld viewer</h1></body></html>", media_type="text/html")


@app.get("/client/replay")
def replay_client() -> Response:
    return Response("<html><body><h1>Coworld replay</h1></body></html>", media_type="text/html")


@app.websocket("/player")
async def player_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    await websocket.send_json({"type": "observation", "tick": 0})
    await websocket.receive_json()
    await websocket.close()


@app.websocket("/global")
async def global_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    await websocket.send_json({"type": "state", "tick": 0})
    await websocket.close()


@app.websocket("/replay")
async def replay_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    await websocket.send_json({"type": "replay_state", "tick": 0})
    await websocket.close()


def main() -> None:
    GameConfig.model_validate_json(read_data(os.environ["COGAME_CONFIG_URI"]))
    uvicorn.run(app, host=os.environ.get("COGAME_HOST", "0.0.0.0"), port=int(os.environ.get("COGAME_PORT", "8080")))


if __name__ == "__main__":
    main()
