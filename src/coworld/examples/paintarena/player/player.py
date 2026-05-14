from __future__ import annotations

import asyncio
import json
import os
from typing import Any, cast

import websockets

from coworld.examples.paintarena.shared.log_shipper import get_logger

logger = get_logger("paintarena.player")


async def main() -> None:
    url = os.environ["COGAMES_ENGINE_WS_URL"]
    logger.info("connecting to %s", url)
    async with websockets.connect(url) as websocket:
        async for raw_message in websocket:
            message = cast(dict[str, Any], json.loads(raw_message))
            if message["type"] == "final":
                logger.info("received final message, exiting")
                return
            if message["type"] == "observation":
                slot = message["slot"]
                await websocket.send(json.dumps({"move": _sweep_move(message, slot)}))


def _sweep_move(message: dict[str, Any], slot: int) -> str:
    position = message["positions"][slot]
    x, y = position
    width = message["width"]
    height = message["height"]
    if slot % 2 == 0:
        if y % 2 == 0 and x < width - 1:
            return "right"
        if y % 2 == 1 and x > 0:
            return "left"
        if y < height - 1:
            return "down"
        return "up"
    if y % 2 == 0 and x > 0:
        return "left"
    if y % 2 == 1 and x < width - 1:
        return "right"
    if y > 0:
        return "up"
    return "down"


asyncio.run(main())
