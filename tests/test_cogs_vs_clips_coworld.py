from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect


def test_cogs_vs_clips_snapshot_exposes_admin_slot_state(tmp_path: Path) -> None:
    game = _new_game(tmp_path)

    snapshot = game.snapshot()

    assert snapshot["protocol"] == "coworld.player.v1"
    assert snapshot["global_protocol"] == "mettagrid.mettascope.live.v1"
    assert snapshot["tick_mode"] == "fixed"
    assert snapshot["human_action_timeout_seconds"] == 5.0
    assert snapshot["slots"][0]["control_state"] == {
        "control_mode": "policy",
        "human_controller_connection_id": None,
        "tick_mode": "fixed",
        "human_action_timeout_seconds": 5.0,
    }


def test_cogs_vs_clips_admin_snapshot_exposes_takeover_player_links(tmp_path: Path) -> None:
    server_module = _load_cogs_vs_clips_server_module()
    game = server_module.CogsVsClipsGame(
        {
            "mission": "machina_1",
            "tokens": ["token 0", "token/1"],
            "max_steps": 3,
            "seed": 0,
            "step_seconds": 0.02,
        },
        results_path=tmp_path / "results.json",
        replay_path=None,
        request_shutdown=lambda: None,
    )

    snapshot = game.admin_snapshot()

    assert all("takeover_url" not in slot for slot in game.snapshot()["slots"])
    for slot_index, slot in enumerate(snapshot["slots"]):
        player_link = urlparse(slot["takeover_url"])
        assert player_link.path == "/clients/player"
        assert parse_qs(player_link.query) == {
            "slot": [str(slot_index)],
            "token": [game.tokens[slot_index]],
            "takeover": ["1"],
        }


def test_cogs_vs_clips_clients_use_slot_admin_and_fullscreen_player() -> None:
    clients_dir = _cogs_vs_clips_root() / "game" / "clients"
    admin_html = (clients_dir / "admin.html").read_text()
    global_html = (clients_dir / "global.html").read_text()
    player_html = (clients_dir / "player.html").read_text()
    replay_html = (clients_dir / "replay.html").read_text()

    assert "takeover_url" in admin_html
    assert "boot_connection" in admin_html
    assert "syncControlValue" in admin_html
    assert "document.activeElement === control" in admin_html
    assert "tickMode.onchange" in admin_html
    assert "slot-summary" in admin_html
    assert "<th>Control</th>" not in admin_html
    assert 'command: "takeover"' not in admin_html
    assert 'command: "release_takeover"' not in admin_html
    assert "background: #101418" in global_html
    assert "background: #161c22" in global_html
    assert "ui-monospace" in global_html
    assert '<iframe id="mettascope" title="MettaScope"></iframe>' in global_html
    assert "mettascope.html?ws=" in global_html
    assert 'id="fallback"' in global_html
    assert '<canvas id="board" width="720" height="720"></canvas>' in global_html
    assert "target.pathname = target.pathname.replace(/\\/clients\\/global$/, path)" in global_html
    assert '<canvas id="screen"></canvas>' in player_html
    assert 'id="actions"' not in player_html
    assert "target.pathname = target.pathname.replace(/\\/clients\\/player$/, path)" in player_html
    assert "tag === `type:${name}`" in player_html
    assert "ArrowUp" in player_html
    assert "Escape" in player_html
    assert 'websocketUrl.pathname.replace(/\\/clients\\/replay(\\/.*)?$/, "/replay$1")' in replay_html


def test_cogs_vs_clips_rollout_routes_preserve_coworld_runtime_contract(tmp_path: Path) -> None:
    server_module = _load_cogs_vs_clips_server_module()
    client = TestClient(
        server_module.create_app(
            {
                "mission": "machina_1",
                "tokens": ["token-0", "token-1"],
                "max_steps": 1,
                "seed": 0,
                "step_seconds": 0.001,
            },
            results_path=tmp_path / "results.json",
            replay_path=tmp_path / "replay.json",
            request_shutdown=lambda: None,
        )
    )

    assert client.get("/healthz").json() == {"ok": True}
    assert client.get("/clients/player", params={"slot": 0, "token": "token-0"}).status_code == 200
    assert client.get("/clients/global").status_code == 200
    assert client.get("/clients/replay", params={"uri": (tmp_path / "replay.json").as_uri()}).status_code == 200

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/player?slot=0&token=bad"):
            pass

    assert exc_info.value.code == 1008

    with (
        client.websocket_connect("/player?slot=0&token=token-0") as player_0,
        client.websocket_connect("/player?slot=1&token=token-1") as player_1,
        client.websocket_connect("/global") as global_viewer,
    ):
        player_0_message = player_0.receive_json()
        player_1_message = player_1.receive_json()
        hello = global_viewer.receive_json()
        assign = global_viewer.receive_json()
        baseline = global_viewer.receive_json()
        messages = []
        for _ in range(20):
            message = global_viewer.receive_json()
            messages.append(message)
            if message["type"] == "done":
                break

    assert player_0_message["type"] == "player_config"
    assert player_0_message["protocol"] == "coworld.player.v1"
    assert player_0_message["slot"] == 0
    assert player_1_message["type"] == "player_config"
    assert player_1_message["slot"] == 1

    assert hello["type"] == "hello"
    assert hello["protocol"] == "mettagrid.mettascope.live.v1"
    assert assign["type"] == "assign"
    assert assign["initial_replay"]["map_size"]
    assert baseline["type"] == "step"
    assert baseline["objects"]
    assert any(message["type"] == "done" for message in messages)


def test_cogs_vs_clips_global_action_updates_policy_action(tmp_path: Path) -> None:
    game = _new_game(tmp_path)
    action_name = next(action_name for action_name in game.episode.action_names if action_name != "noop")

    game.handle_global_message({"type": "action", "agent_id": 0, "action_name": action_name})
    game.episode.apply_actions()

    assert game.episode.latest_policy_actions[0].action_name == action_name
    assert game.episode.latest_action_indices[0] == game.episode.action_names.index(action_name)


def test_cogs_vs_clips_records_compact_mettascope_replay(tmp_path: Path) -> None:
    server_module = _load_cogs_vs_clips_server_module()
    replay_path = tmp_path / "replay.json"
    game = server_module.CogsVsClipsGame(
        {
            "mission": "machina_1",
            "tokens": ["token-0", "token-1"],
            "max_steps": 3,
            "seed": 0,
            "step_seconds": 0.02,
        },
        results_path=tmp_path / "results.json",
        replay_path=replay_path,
        request_shutdown=lambda: None,
    )

    game.episode.apply_actions()
    game.sim.step()
    message = game.record_replay_step()
    results = game.results()

    replay = json.loads(replay_path.read_text(encoding="utf-8"))
    assert message["type"] == "step"
    assert results["steps"] == 1
    assert replay["version"] == 4
    assert replay["max_steps"] == 1
    assert replay["num_agents"] == 2
    assert replay["objects"]
    assert "events" not in replay
    assert "results" not in replay


def test_cogs_vs_clips_live_replay_includes_mettascope_render_config(tmp_path: Path) -> None:
    game = _new_game(tmp_path)

    render_config = game.initial_replay["mg_config"]["game"]["render"]

    assert render_config["assets"]["junction"][0]["asset"] == "junction.working"
    assert render_config["assets"]["c:aligner"][0]["asset"] == "aligner_station"
    assert render_config["assets"]["c:scrambler"][0]["asset"] == "scrambler_station"
    assert render_config["assets"]["c:miner"][0]["asset"] == "miner_station"
    assert render_config["assets"]["c:scout"][0]["asset"] == "scout_station"
    assert render_config["hud1"]["resource"] == "hp"
    assert render_config["hud2"]["resource"] == "energy"


def test_cogs_vs_clips_replay_client_redirects_to_mettascope(tmp_path: Path) -> None:
    server_module = _load_cogs_vs_clips_server_module()
    replay_path = tmp_path / "replay.json"
    replay_path.write_text(json.dumps({"results": {"steps": 2}, "frames": [{"tick": 0}]}), encoding="utf-8")
    client = TestClient(server_module.create_replay_app())

    assert client.get("/healthz").json() == {"ok": True}
    response = client.get(
        "/clients/replay",
        params={"uri": replay_path.as_uri()},
        follow_redirects=False,
    )
    location = response.headers["location"]
    replay_url = parse_qs(urlparse(location).query)["replay"][0]

    assert response.status_code == 307
    assert location.startswith(server_module.METTASCOPE_REPLAY_URL_PREFIX)
    assert replay_url.startswith("http://testserver/replay-data?")
    replay_response = client.get("/replay-data", params={"uri": replay_path.as_uri()})
    assert json.loads(replay_response.content) == {"results": {"steps": 2}, "frames": [{"tick": 0}]}
    assert replay_response.headers["access-control-allow-origin"] == "*"

    with client.websocket_connect(f"/replay?{urlencode({'uri': replay_path.as_uri()})}") as websocket:
        replay_message = websocket.receive_json()
        websocket.send_json({"command": "pause"})
        control_message = websocket.receive_json()

    assert replay_message == {"type": "replay", "results": {"steps": 2}, "frames": [{"tick": 0}]}
    assert control_message == {"type": "control", "command": {"command": "pause"}}


def _new_game(tmp_path: Path):
    server_module = _load_cogs_vs_clips_server_module()
    return server_module.CogsVsClipsGame(
        {
            "mission": "machina_1",
            "tokens": ["token-0", "token-1"],
            "max_steps": 3,
            "seed": 0,
            "step_seconds": 0.02,
        },
        results_path=tmp_path / "results.json",
        replay_path=None,
        request_shutdown=lambda: None,
    )


def _cogs_vs_clips_root() -> Path:
    return Path(__file__).resolve().parents[1] / "src" / "coworld" / "examples" / "cogs_vs_clips"


def _load_cogs_vs_clips_server_module():
    spec = importlib.util.spec_from_file_location(
        "cogs_vs_clips_server_test",
        _cogs_vs_clips_root() / "game" / "server.py",
    )
    assert spec is not None
    assert spec.loader is not None
    server_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(server_module)
    return server_module
