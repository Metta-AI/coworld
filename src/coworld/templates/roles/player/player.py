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
    async with websockets.connect(ws_url) as websocket:
        async for message in websocket:
            observation = json.loads(message)
            await websocket.send(json.dumps(choose_action(observation)))


def main() -> None:
    asyncio.run(run(os.environ["COWORLD_PLAYER_WS_URL"]))


if __name__ == "__main__":
    main()
