# Commissioner Template

The commissioner is a WebSocket service that schedules league rounds and episodes. Use the default commissioner when
round-robin behavior is enough; use this scaffold when a Coworld needs game-specific league logic.

Contract reference: `coworld/docs/roles/COMMISSIONER.md`.

Files:

- `commissioner.py` - FastAPI `/round` scaffold using `coworld.commissioner.protocol` models.
- `commissioner_manifest_entry.json` - manifest fragment for a custom commissioner runnable.
- `Dockerfile` - minimal image shape for packaging the commissioner runnable.
