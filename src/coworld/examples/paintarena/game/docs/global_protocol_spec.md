# Paint Arena Global Protocol

Browsers request `GET /client/global` to load the global client; the page and its websocket follow the contract in
[GAME_RUNTIME_README.md § Browser Clients](../../../../GAME_RUNTIME_README.md#browser-clients). By default the client
opens `/global`.

The server sends a JSON state snapshot immediately on connect and then sends updated snapshots while the episode runs:

```json
{
  "type": "state",
  "width": 12,
  "height": 8,
  "positions": [
    [0, 0],
    [11, 7]
  ],
  "tile_owners": [0, -1, -1, 1],
  "scores": [0, 0],
  "tick": 0,
  "max_ticks": 100,
  "paused": false,
  "tick_rate": 5,
  "done": false
}
```

When the server is started with `COGAME_LOAD_REPLAY_URI=<uri>`, browsers request `GET /client/replay` to load the replay
client. The replay client opens the `/replay` websocket to receive replay data and send control commands.

For local development, browsers may request `GET /client/admin` and open `/admin` as a websocket. The admin websocket
accepts:

```json
{ "command": "pause" }
{ "command": "resume" }
{ "command": "tick_rate", "tick_rate": 15 }
```

The final player message carries a state snapshot with `type: "final"` and `done: true`. Scores are the number of tiles
currently painted with each player's color.
