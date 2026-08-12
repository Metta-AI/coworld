"""Player runnables must disable the client WebSocket keepalive pong timeout.

Certified game engines answer WebSocket Ping frames, but previously deployed
engines may not. The Python `websockets` client's default keepalive
(ping_interval=20, ping_timeout=20) then silently closes the connection ~40 s
into a hosted episode — long after the short local smoke episode has passed
(coworld#41). Every bundled player therefore retains ping_timeout=None.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import runpy
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import websockets

import coworld

TEMPLATE_PLAYER = Path(coworld.__file__).parent / "templates" / "roles" / "player" / "player.py"
PAINTARENA_PLAYER = Path(coworld.__file__).parent / "examples" / "paintarena" / "player" / "player.py"


def _load_template_player() -> ModuleType:
    spec = importlib.util.spec_from_file_location("coworld_template_player", TEMPLATE_PLAYER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _recording_connect(captured: dict[str, Any]):
    real_connect = websockets.connect

    def connect(url: str, **kwargs: Any):
        captured.update(kwargs)
        return real_connect(url, **kwargs)

    return connect


def test_template_player_disables_client_keepalive(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    module = _load_template_player()
    monkeypatch.setattr(module.websockets, "connect", _recording_connect(captured))

    actions: list[dict[str, Any]] = []

    async def run() -> None:
        async def game(ws) -> None:
            await ws.send(json.dumps({"type": "observation"}))
            actions.append(json.loads(await ws.recv()))
            await ws.close()

        server = await websockets.serve(game, "127.0.0.1", 0)
        port = next(iter(server.sockets)).getsockname()[1]
        try:
            await module.run(f"ws://127.0.0.1:{port}")
        finally:
            server.close()
            await server.wait_closed()

    asyncio.run(run())

    assert actions == [{"type": "action", "action": "noop"}]
    assert captured["ping_timeout"] is None


def test_paintarena_player_disables_client_keepalive(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(websockets, "connect", _recording_connect(captured))

    async def run() -> None:
        async def game(ws) -> None:
            await ws.send(json.dumps({"type": "final"}))
            await ws.wait_closed()

        server = await websockets.serve(game, "127.0.0.1", 0)
        port = next(iter(server.sockets)).getsockname()[1]
        monkeypatch.setenv("COWORLD_PLAYER_WS_URL", f"ws://127.0.0.1:{port}")
        try:
            # The player module runs asyncio.run(main()) at import time, so
            # execute it as the script it is, on its own loop in a thread.
            await asyncio.to_thread(runpy.run_path, str(PAINTARENA_PLAYER))
        finally:
            server.close()
            await server.wait_closed()

    asyncio.run(run())

    assert captured["ping_timeout"] is None
