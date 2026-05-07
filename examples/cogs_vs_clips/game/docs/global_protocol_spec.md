# Global Protocol

Connect to `/global` with a websocket. The endpoint accepts viewers before or during an episode and speaks the
`mettagrid.mettascope.live.v1` live-replay protocol used by the websocket-capable MettaScope build.

The first message is a small readiness frame:

```json
{
  "type": "hello",
  "protocol": "mettagrid.mettascope.live.v1",
  "status": {
    "mission": "cogsguard",
    "connected_players": 1,
    "num_agents": 2,
    "done": false
  }
}
```

The next message assigns the global viewer to the live replay:

```json
{
  "type": "assign",
  "protocol": "mettagrid.mettascope.live.v1",
  "agent_id": -1,
  "initial_replay": {
    "version": 2,
    "action_names": ["noop", "move_north"],
    "item_names": ["energy"],
    "type_names": ["agent", "wall"],
    "map_size": [24, 24],
    "num_agents": 2,
    "mg_config": {}
  },
  "status": {
    "mission": "cogsguard",
    "connected_players": 1,
    "num_agents": 2,
    "done": false
  }
}
```

The `hello` and `assign` frames intentionally keep status metadata under `status` without a nested `step` key. This keeps
older Emscripten MettaScope builds from mistaking those pre-replay envelopes for replay step frames.

The server then sends a one-time static wall frame:

```json
{
  "type": "walls",
  "protocol": "mettagrid.mettascope.live.v1",
  "step": 0,
  "objects": [{"id": 1, "type_name": "wall", "location": [0, 0], "alive": true}]
}
```

Subsequent messages are MettaGrid replay step frames for dynamic objects:

```json
{
  "type": "step",
  "protocol": "mettagrid.mettascope.live.v1",
  "step": 1,
  "objects": [
    {
      "id": 10,
      "type_name": "agent",
      "location": [6, 6],
      "agent_id": 0,
      "is_agent": true
    }
  ],
  "episode_stats": {},
  "state": {
    "type": "state",
    "scores": [0.0, 0.0],
    "paused": false,
    "done": false
  }
}
```

The HTTP `/global` client loads the bundled websocket-capable MettaScope from `/mettascope/mettascope.html?ws=...` when
the Docker image includes it, and keeps a lightweight canvas fallback connected to the same `/global` websocket. A
mid-episode viewer receives a fresh `assign` frame and the latest step frame, so it can render from its join point.

When the episode completes, the server sends a terminal frame:

```json
{
  "type": "done",
  "protocol": "mettagrid.mettascope.live.v1",
  "steps": 120,
  "status": {
    "mission": "cogsguard",
    "done": true,
    "scores": [1.0, 0.0],
    "num_agents": 2,
    "connected_players": 1,
    "action_names": ["noop", "move_north"],
    "protocol": "mettagrid.mettascope.live.v1"
  }
}
```

The global websocket may also receive MettaScope action/control messages:

```json
{ "type": "action", "agent_id": 0, "action_name": "move_north" }
{ "type": "control", "command": "pause" }
{ "type": "control", "command": "speed", "speed": 5.0 }
```

Replay mode starts the same image with `COGAME_LOAD_REPLAY_PATH`, serves `GET /replay`, and sends the saved live-replay
artifact over `WEBSOCKET /replay`.
