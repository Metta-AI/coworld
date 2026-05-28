from __future__ import annotations

import asyncio
import json
import os
from typing import Literal

import websockets
from pydantic import BaseModel, Field


class PlayerConfig(BaseModel):
    type: Literal["player_config"]
    protocol: Literal["coworld.player.v1"]
    slot: int
    connection_id: str
    action_names: list[str] = Field(min_length=1)
    policy_env: dict[str, object]


class Observation(BaseModel):
    type: Literal["observation"]
    protocol: Literal["coworld.player.v1"]
    slot: int
    step: int
    observation: list[tuple[int, int, int]]


async def main() -> None:
    preferred_actions = ("move_north", "move_east", "move_south", "move_west", "noop")
    async with websockets.connect(os.environ["COWORLD_PLAYER_WS_URL"]) as websocket:
        config = PlayerConfig.model_validate(json.loads(await websocket.recv()))
        async for raw_message in websocket:
            message = json.loads(raw_message)
            if message["type"] == "observation":
                observation = Observation.model_validate(message)
                action_name = next(
                    (candidate for candidate in preferred_actions if candidate in config.action_names),
                    config.action_names[observation.step % len(config.action_names)],
                )
                await websocket.send(
                    json.dumps(
                        {
                            "type": "action",
                            "action_name": action_name,
                            "policy_infos": {"policy_name": "cvcstarter"},
                            "request_id": f"step-{observation.step}",
                        }
                    )
                )
            elif message["type"] == "final":
                return


asyncio.run(main())
