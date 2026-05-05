# Tic-Tac-Toe Player Protocol

Browsers request `GET /player?slot=<slot>&token=<token>` to load the player client. The client forwards the same query
params when it opens the `/player?slot=<slot>&token=<token>` websocket.

The server sends a JSON turn message:

```json
{
  "type": "turn",
  "slot": 0,
  "board": ["", "", "", "", "", "", "", "", ""]
}
```

The player replies with a move:

```json
{
  "move": 0
}
```

`move` is a zero-based board index from `0` to `8`. Invalid or occupied moves are replaced by the first empty square.
Bad tokens are rejected during the websocket handshake.
