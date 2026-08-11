# Player Template

The player connects to the game-owned `/player` WebSocket URL provided by `COWORLD_PLAYER_WS_URL`, receives
game-specific observations, sends game-specific actions, and exits when the episode ends.

Keep `ping_timeout=None` on the `websockets.connect` call: game engines are not guaranteed to answer WebSocket
ping frames, and the client's default pong timeout would silently drop the connection ~40 s into a hosted
episode — long after the short local smoke episode has already passed. Keepalive pings are still sent; the
client just never kills the connection over a missing pong.

Contract reference: `coworld/docs/roles/PLAYER.md`.

Files:

- `player.py` - async WebSocket player loop scaffold.
- `Dockerfile` - minimal image shape for packaging the player runnable.
