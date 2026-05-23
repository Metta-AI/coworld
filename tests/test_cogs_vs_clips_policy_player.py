from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

POLICY_PLAYER_PATH = Path(__file__).resolve().parents[3] / "worlds" / "cogs_vs_clips" / "player" / "policy_player.py"

policy_player_spec = importlib.util.spec_from_file_location("cogs_vs_clips_policy_player", POLICY_PLAYER_PATH)
assert policy_player_spec is not None
policy_player = importlib.util.module_from_spec(policy_player_spec)
assert policy_player_spec.loader is not None
sys.modules[policy_player_spec.name] = policy_player
policy_player_spec.loader.exec_module(policy_player)
ReferencePlayer = policy_player.ReferencePlayer
run_reference_player = policy_player.run_reference_player


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


def test_reference_player_prefers_noop() -> None:
    player = ReferencePlayer()
    player.configure(_player_config(action_names=["move_north", "noop"]))

    assert player.action_for_observation(_observation()) == {
        "type": "action",
        "action_name": "noop",
        "policy_infos": {"policy_name": "coworld-reference-player"},
        "request_id": "step-4",
    }


def test_reference_player_rotates_when_noop_is_unavailable() -> None:
    player = ReferencePlayer()
    player.configure(_player_config(slot=1, action_names=["left", "right", "up"]))

    assert player.action_for_observation(_observation(step=4))["action_name"] == "up"


def test_reference_player_sends_actions(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_websocket = FakeWebSocket(
        [
            _player_config(action_names=["noop", "move_north"]),
            _observation(),
            {"type": "final", "protocol": "coworld.player.v1"},
        ]
    )

    monkeypatch.setattr(policy_player.websockets, "connect", lambda _url: fake_websocket)

    asyncio.run(run_reference_player(player_ws_url="ws://engine/player?slot=0&token=token"))

    assert fake_websocket.sent == [
        {
            "type": "action",
            "action_name": "noop",
            "policy_infos": {"policy_name": "coworld-reference-player"},
            "request_id": "step-4",
        }
    ]


def test_reference_player_main_uses_coworld_player_ws_url(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[str] = []

    async def fake_run_reference_player(*, player_ws_url: str) -> None:
        captured.append(player_ws_url)

    monkeypatch.setattr(policy_player, "run_reference_player", fake_run_reference_player)
    monkeypatch.setenv("COWORLD_PLAYER_WS_URL", "ws://engine/player?slot=0&token=token")

    policy_player.main()

    assert captured == ["ws://engine/player?slot=0&token=token"]


def _player_config(slot: int = 0, action_names: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "player_config",
        "protocol": "coworld.player.v1",
        "slot": slot,
        "connection_id": f"player-{slot}",
        "action_names": action_names or ["noop", "move_north"],
        "policy_env": {},
    }


def _observation(step: int = 4) -> dict[str, Any]:
    return {
        "type": "observation",
        "protocol": "coworld.player.v1",
        "slot": 0,
        "step": step,
        "observation": [(254, 1, 7), (255, 255, 255)],
    }
