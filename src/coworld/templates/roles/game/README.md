# Game Template

This scaffold demonstrates `platform-hosted` players. Authors may instead choose `game-hosted` file players;
read [Choose a Player Runtime](../../../docs/PLAYER_RUNTIMES.md) before adopting the scaffold.
Game-hosted execution requires implementing the game's file interface and per-seat output contract.


The game owns episode truth. Replace the scaffold routes with game-specific protocol messages, state transitions,
browser clients, results, and replay serialization.

Contract reference: `coworld/docs/roles/GAME.md`.

Files:

- `game_server.py` - FastAPI scaffold for the Coworld game runtime.
- `Dockerfile` - minimal image shape for packaging the game runnable.
