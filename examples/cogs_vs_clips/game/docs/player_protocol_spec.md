# Player Protocol

Connect to `/player?slot=<slot>&token=<token>` with a websocket. `slot` is zero-indexed and `token` must match the token
supplied by the Coworld runner for that slot.

The first accepted message is a rendering/configuration subset for the slot:

```json
{
  "type": "player_config",
  "mission": "cogsguard",
  "slot": 0,
  "num_agents": 2,
  "action_names": ["noop", "move_north", "move_south"],
  "observation_shape": [500, 3],
  "observation": {
    "width": 13,
    "height": 13,
    "features": [{"id": 6, "name": "tag", "normalization": 10.0}],
    "tags": ["agent", "wall"],
    "global_location": 254,
    "empty_location": 255
  }
}
```

At each simulator step the engine sends the raw MettaGrid token observation:

```json
{
  "type": "step",
  "mission": "cogsguard",
  "slot": 0,
  "step": 1,
  "observation": [[254, 1, 0], [102, 6, 1]],
  "action_names": ["noop", "move_north", "move_south"]
}
```

Observation tokens are `[packed_location, feature_id, value]`. `packed_location == 254` is a global feature and
`packed_location == 255` is padding. Spatial locations use `row = packed_location // 16` and
`col = packed_location % 16` within the configured egocentric observation window.

The player responds with an action index:

```json
{ "action_index": 0 }
```

or an action name:

```json
{ "action_name": "noop" }
```

Invalid or missing actions are treated as `noop`. A player can reconnect to the same slot with the same token while the
episode is running; disconnected or not-yet-connected slots advance with their latest submitted action, initially
`noop`.
