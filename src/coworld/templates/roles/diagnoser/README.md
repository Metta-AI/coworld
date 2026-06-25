# Diagnoser Template

The diagnoser is a one-shot process that consumes an episode bundle and a target policy reference, then writes a
diagnosis zip.

Contract reference: `coworld/docs/roles/DIAGNOSER.md`.

Files:

- `diagnoser.py` - bundle reader and diagnosis zip writer scaffold.
- `Dockerfile` - minimal image shape for packaging the diagnoser runnable.
