# Tic-Tac-Toe Global Protocol

Viewers connect to `/global`.

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
