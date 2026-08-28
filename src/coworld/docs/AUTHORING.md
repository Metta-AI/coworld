# Author a Coworld

The task-focused authoring guide lives at
[docs.softmax.com/coworld/build-a-coworld/overview](https://docs.softmax.com/coworld/build-a-coworld/overview). Its
source is mirrored into this repository under
[`docs/build-a-coworld/`](../../../docs/build-a-coworld/overview.mdx).

Follow that guide from game design through local checks, certification, upload, and hosted verification. This page is
kept as a stable entry point for older links; it no longer duplicates the guide.

## Exact technical references

- [Coworld manifest](COWORLD_MANIFEST.md) for fields, variants, certification fixtures, and generated schemas.
- [Game role](roles/GAME.md) and [player role](roles/PLAYER.md) for container and protocol behavior.
- [Coworld lifecycle](LIFECYCLE.md) for local and hosted execution.
- [Static replay viewers](STATIC_REPLAY_VIEWERS.md) when the replay client is a browser-only bundle.
- [Bedrock for Coworld players](BEDROCK.md) when a bundled player calls a hosted model.
- [Paint Arena](../examples/paintarena/README.md) for the smallest complete implementation.

Use built-in help for the installed command surface:

```bash
uv run coworld build --help
uv run coworld certify --help
uv run coworld upload-coworld --help
```
