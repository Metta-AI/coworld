# Player Protocol

Connect to `/player?slot=<slot>&token=<token>` with a websocket. `slot` is zero-indexed and `token` must match the token
supplied by the Coworld runner for that slot.

The first accepted message is a rendering/configuration subset for the slot:

```json
{
  "type": "player_config",
  "protocol": "coworld.player.v1",
  "mission": "cogsguard",
  "slot": 0,
  "connection_id": "player-0",
  "num_agents": 2,
  "action_names": ["noop", "move_north", "move_south"],
  "observation_shape": [500, 3],
  "policy_env": {
    "action_names": ["noop", "move_north", "move_south"],
    "num_agents": 2,
    "observation_shape": [500, 3],
    "egocentric_shape": [13, 13]
  },
  "observation": {
    "width": 13,
    "height": 13,
    "features": [{"id": 6, "name": "tag", "normalization": 10.0}],
    "tags": ["agent", "wall"],
    "global_location": 254,
    "empty_location": 255
  },
  "control_state": {
    "control_mode": "policy",
    "human_controller_connection_id": null,
    "tick_mode": "fixed",
    "human_action_timeout_seconds": 5.0
  }
}
```

At each simulator step the engine sends the raw MettaGrid token observation:

```json
{
  "type": "observation",
  "protocol": "coworld.player.v1",
  "mission": "cogsguard",
  "slot": 0,
  "step": 1,
  "observation": [[254, 1, 0], [102, 6, 1]],
  "scores": [0.0, 0.0],
  "is_human_controlled": false,
  "control_state": {
    "control_mode": "policy",
    "human_controller_connection_id": null,
    "tick_mode": "fixed",
    "human_action_timeout_seconds": 5.0
  }
}
```

Observation tokens are `[packed_location, feature_id, value]`. `packed_location == 254` is a global feature and
`packed_location == 255` is padding. Spatial locations use `row = packed_location // 16` and
`col = packed_location % 16` within the configured egocentric observation window.

The player responds with an action index:

```json
{ "type": "action", "action_index": 0 }
```

or an action name:

```json
{ "type": "action", "action_name": "noop", "policy_infos": { "reason": "blocked" }, "request_id": "step-1" }
```

Default control is policy. Any non-controller connection can keep submitting policy actions for its slot. A player
connection can explicitly take human control:

```json
{ "type": "takeover" }
```

Only that connection's actions control the slot while takeover is active. Policy connections still receive
observations and may keep submitting actions and policy infos, but those actions are ignored until human control is
released:

```json
{ "type": "release_takeover" }
```

If a human-controlled slot is idle for a tick, the applied action is `noop`. Invalid or missing actions are treated as
`noop`. A player can reconnect to the same slot with the same token while the episode is running.
