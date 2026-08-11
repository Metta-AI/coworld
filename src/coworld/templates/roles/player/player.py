from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import websockets


def choose_action(observation: dict[str, Any]) -> dict[str, str]:
    if observation["type"] == "observation":
        return {"type": "action", "action": "noop"}
    raise ValueError(f"Unsupported observation type: {observation['type']}")


async def run(ws_url: str) -> None:
    # ping_timeout=None: game engines are not required to answer WebSocket ping
    # frames, and the default 20s pong timeout would silently close a healthy
    # connection mid-episode when they don't (coworld#41). Keepalive pings are
    # still sent so the connection carries a minimum of outbound traffic.
    async with websockets.connect(ws_url, ping_timeout=None) as websocket:
        async for message in websocket:
            observation = json.loads(message)
            await websocket.send(json.dumps(choose_action(observation)))


def main() -> None:
    asyncio.run(run(os.environ["COWORLD_PLAYER_WS_URL"]))


if __name__ == "__main__":
    main()
