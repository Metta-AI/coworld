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
    # ping_timeout=None protects previously deployed games that don't answer
    # WebSocket Ping frames; certification now requires new games to answer.
    # Keepalive pings are still sent without closing on a missing Pong.
    async with websockets.connect(ws_url, ping_timeout=None) as websocket:
        async for message in websocket:
            observation = json.loads(message)
            await websocket.send(json.dumps(choose_action(observation)))


def main() -> None:
    asyncio.run(run(os.environ["COWORLD_PLAYER_WS_URL"]))


if __name__ == "__main__":
    main()
