from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Callable
from typing import Literal

import websockets
from pydantic import BaseModel

from mettagrid.policy.loader import initialize_or_load_policy
from mettagrid.policy.policy import MultiAgentPolicy
from mettagrid.policy.policy_env_interface import PolicyEnvInterface
from mettagrid.simulator import AgentObservation
from mettagrid.simulator.interface import ObservationToken
from mettagrid.util.uri_resolvers.schemes import policy_spec_from_uri


class PolicyPlayerConfig(BaseModel):
    type: Literal["player_config"]
    protocol: Literal["coworld.player.v1"]
    slot: int
    connection_id: str
    action_names: list[str]
    policy_env: PolicyEnvInterface


class PolicyPlayerObservation(BaseModel):
    type: Literal["observation"]
    protocol: Literal["coworld.player.v1"]
    slot: int
    step: int
    observation: list[tuple[int, int, int]]


PolicyFactory = Callable[[str, PolicyEnvInterface, str], MultiAgentPolicy]


def load_policy(policy_uri: str, policy_env: PolicyEnvInterface, device: str) -> MultiAgentPolicy:
    policy_spec = policy_spec_from_uri(policy_uri, device=device)
    return initialize_or_load_policy(policy_env, policy_spec, device_override=device)


class MettaPolicyPlayer:
    def __init__(
        self,
        *,
        policy_uri: str,
        device: str = "cpu",
        policy_factory: PolicyFactory = load_policy,
    ):
        self.policy_uri = policy_uri
        self.device = device
        self.policy_factory = policy_factory
        self.config: PolicyPlayerConfig | None = None
        self.policy: MultiAgentPolicy | None = None

    def configure(self, raw_message: dict[str, object]) -> None:
        config = PolicyPlayerConfig.model_validate(raw_message)
        self.config = config
        self.policy = self.policy_factory(self.policy_uri, config.policy_env, self.device)

    def action_for_observation(self, raw_message: dict[str, object]) -> dict[str, object]:
        observation_message = PolicyPlayerObservation.model_validate(raw_message)
        assert self.config is not None
        assert self.policy is not None
        agent_policy = self.policy.agent_policy(self.config.slot)
        observation = decode_triplet_observation(
            observation_message.observation,
            self.config.policy_env,
            self.config.slot,
        )
        action = agent_policy.step(observation)
        return {
            "type": "action",
            "action_name": action.name,
            "policy_infos": agent_policy.infos,
            "request_id": f"step-{observation_message.step}",
        }


def decode_triplet_observation(
    raw_observation: list[tuple[int, int, int]],
    policy_env: PolicyEnvInterface,
    agent_id: int,
) -> AgentObservation:
    features = {feature.id: feature for feature in policy_env.obs_features}
    tokens: list[ObservationToken] = []
    for raw_token in raw_observation:
        location, feature_id, value = raw_token
        if feature_id == 0xFF:
            break
        tokens.append(
            ObservationToken(
                feature=features[feature_id],
                value=value,
                raw_token=(location, feature_id, value),
            )
        )
    return AgentObservation(agent_id=agent_id, tokens=tokens)


async def run_policy_player(
    *,
    engine_ws_url: str,
    policy_uri: str,
    device: str = "cpu",
    policy_factory: PolicyFactory = load_policy,
) -> None:
    player = MettaPolicyPlayer(policy_uri=policy_uri, device=device, policy_factory=policy_factory)
    async with websockets.connect(engine_ws_url) as websocket:
        async for raw_message in websocket:
            message = json.loads(raw_message)
            if message["type"] == "player_config":
                player.configure(message)
            elif message["type"] == "observation":
                await websocket.send(json.dumps(player.action_for_observation(message)))
            elif message["type"] == "final":
                return


def main() -> None:
    asyncio.run(
        run_policy_player(
            engine_ws_url=os.environ["COGAMES_ENGINE_WS_URL"],
            policy_uri=os.environ["COGAMES_POLICY_URI"],
            device=os.environ.get("COGAMES_POLICY_DEVICE", "cpu"),
        )
    )


if __name__ == "__main__":
    main()
