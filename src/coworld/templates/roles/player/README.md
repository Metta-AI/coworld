# Player Template

The player connects to the game-owned `/player` WebSocket URL provided by `COWORLD_PLAYER_WS_URL`, receives
game-specific observations, sends game-specific actions, and exits when the episode ends.

Contract reference: `coworld/docs/roles/PLAYER.md`.

Files:

- `player.py` - async WebSocket player loop scaffold.
- `Dockerfile` - minimal image shape for packaging the player runnable.
