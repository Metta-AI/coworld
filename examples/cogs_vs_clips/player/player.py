from __future__ import annotations

import asyncio
import json
import os

import websockets


async def main() -> None:
    async with websockets.connect(os.environ["COGAMES_ENGINE_WS_URL"]) as websocket:
        async for raw_message in websocket:
            message = json.loads(raw_message)
            if message["type"] == "step":
                await websocket.send(json.dumps({"action_index": 0}))
            elif message["type"] == "final":
                return


asyncio.run(main())
