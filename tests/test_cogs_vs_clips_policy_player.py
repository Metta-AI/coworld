from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from mettagrid.config.id_map import ObservationFeatureSpec
from mettagrid.policy.policy import AgentPolicy, MultiAgentPolicy
from mettagrid.policy.policy_env_interface import PolicyEnvInterface
from mettagrid.simulator import Action, AgentObservation

POLICY_PLAYER_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "coworld"
    / "examples"
    / "cogs_vs_clips"
    / "player"
    / "policy_player.py"
)

policy_player_spec = importlib.util.spec_from_file_location("cogs_vs_clips_policy_player", POLICY_PLAYER_PATH)
assert policy_player_spec is not None
policy_player = importlib.util.module_from_spec(policy_player_spec)
assert policy_player_spec.loader is not None
sys.modules[policy_player_spec.name] = policy_player
policy_player_spec.loader.exec_module(policy_player)
decode_triplet_observation = policy_player.decode_triplet_observation
run_policy_player = policy_player.run_policy_player


class FakeAgentPolicy(AgentPolicy):
    def __init__(self):
        super().__init__(_policy_env())
        self._infos = {"intent": "north"}
        self.observation: AgentObservation | None = None

    def step(self, obs: AgentObservation) -> Action:
        self.observation = obs
        return Action("move_north")


class FakePolicy(MultiAgentPolicy):
    def __init__(self, agent_policy: FakeAgentPolicy):
        super().__init__(_policy_env())
        self._agent_policy = agent_policy

    def agent_policy(self, _agent_id: int) -> FakeAgentPolicy:
        return self._agent_policy


class FakeWebSocket:
    def __init__(self, messages: list[dict[str, Any]]):
        self.messages = [json.dumps(message) for message in messages]
        self.sent: list[dict[str, Any]] = []

    async def __aenter__(self) -> "FakeWebSocket":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    def __aiter__(self) -> "FakeWebSocket":
        return self

    async def __anext__(self) -> str:
        if not self.messages:
            raise StopAsyncIteration
        return self.messages.pop(0)

    async def send(self, raw_message: str) -> None:
        self.sent.append(json.loads(raw_message))


def test_decode_triplet_observation_builds_agent_observation() -> None:
    observation = decode_triplet_observation(
        [(254, 1, 7), (255, 255, 255), (42, 1, 9)],
        _policy_env(),
        agent_id=3,
    )

    assert observation.agent_id == 3
    assert len(observation.tokens) == 1
    token = observation.tokens[0]
    assert token.feature.name == "energy"
    assert token.value == 7
    assert token.raw_token == (254, 1, 7)


def test_policy_player_uses_configured_policy_and_forwards_infos(monkeypatch: pytest.MonkeyPatch) -> None:
    agent_policy = FakeAgentPolicy()
    fake_websocket = FakeWebSocket(
        [
            _player_config(),
            _observation(),
            {"type": "final", "protocol": "coworld.player.v1"},
        ]
    )

    monkeypatch.setattr(policy_player.websockets, "connect", lambda _url: fake_websocket)

    asyncio.run(
        run_policy_player(
            engine_ws_url="ws://engine/player?slot=0&token=token",
            policy_uri="metta://policy/fake",
            policy_factory=lambda _uri, _env, _device: FakePolicy(agent_policy),
        )
    )

    assert fake_websocket.sent == [
        {
            "type": "action",
            "action_name": "move_north",
            "policy_infos": {"intent": "north"},
            "request_id": "step-4",
        }
    ]
    assert agent_policy.observation is not None
    assert agent_policy.observation.agent_id == 0


def _player_config() -> dict[str, Any]:
    return {
        "type": "player_config",
        "protocol": "coworld.player.v1",
        "slot": 0,
        "connection_id": "player-0",
        "action_names": ["noop", "move_north"],
        "policy_env": _policy_env().model_dump(mode="json"),
    }


def _observation() -> dict[str, Any]:
    return {
        "type": "observation",
        "protocol": "coworld.player.v1",
        "slot": 0,
        "step": 4,
        "observation": [(254, 1, 7), (255, 255, 255)],
    }


def _policy_env() -> PolicyEnvInterface:
    return PolicyEnvInterface(
        obs_features=[ObservationFeatureSpec(id=1, name="energy", normalization=10.0)],
        tags=[],
        action_names=["noop", "move_north"],
        num_agents=1,
        observation_shape=(2, 3),
        egocentric_shape=(1, 1),
    )
