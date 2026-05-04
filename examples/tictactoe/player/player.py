from __future__ import annotations

import asyncio
import json
import os

import websockets
from websockets.exceptions import ConnectionClosed


async def main() -> None:
    async with websockets.connect(os.environ["COGAMES_ENGINE_WS_URL"]) as websocket:
        try:
            async for raw_message in websocket:
                message = json.loads(raw_message)
                if message["type"] == "turn":
                    board = message["board"]
                    await websocket.send(json.dumps({"move": board.index("")}))
                if message["type"] == "final":
                    return
        except ConnectionClosed:
            return


asyncio.run(main())
