# Tic-Tac-Toe Global Protocol

Browsers request `GET /global` to load the global client. The client forwards the same query params when it opens the
`/global` websocket.

The server sends a JSON state snapshot immediately on connect:

```json
{
  "type": "state",
  "board": ["", "", "", "", "", "", "", "", ""],
  "moves": [],
  "winner": -1,
  "done": false
}
```

The final player message also carries a state snapshot with `type: "final"` and `done: true`.
`winner` is `0`, `1`, or `-1` for a draw or unfinished episode.
