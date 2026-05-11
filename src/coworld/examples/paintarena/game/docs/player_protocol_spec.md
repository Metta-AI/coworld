# Paint Arena Player Protocol

Browsers request `GET /clients/player?slot=<slot>&token=<token>` to load the player client. The client forwards the
same query params when it opens the `/player?slot=<slot>&token=<token>` websocket.

The server sends an observation every tick:

```json
{
  "type": "observation",
  "slot": 0,
  "width": 12,
  "height": 8,
  "positions": [[0, 0], [11, 7]],
  "tile_owners": [0, -1, -1, 1],
  "scores": [0, 0],
  "tick": 0,
  "max_ticks": 100,
  "paused": false,
  "tick_rate": 5,
  "done": false
}
```

The player replies with its preferred movement direction:

```json
{
  "move": "right"
}
```

`move` is one of `up`, `down`, `left`, `right`, or `stay`. After movement, the tile under each player is painted with
that player's color, overwriting any previous owner. Invalid moves become `stay`. Bad tokens are rejected during the
websocket handshake.
