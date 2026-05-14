# Paint Arena Coworld Example

Paint Arena is the smallest complete Coworld example in this package. It has one game image and one bundled player
entrypoint.

The game is two-player and tick-based. Each player moves around a grid and paints the tile they are standing on.
Painting overwrites the previous owner. Final scores are the number of tiles painted with each player's color.

## Build Images

From this directory:

```bash
docker build --platform=linux/amd64 -t coworld-paintarena:latest .
```

From the Coworld package root (`packages/coworld/src/coworld`):

```bash
docker build --platform=linux/amd64 -t coworld-paintarena:latest examples/paintarena
```

Use `linux/amd64` for images that will be uploaded to Softmax, including when building from Apple Silicon.

## Play Locally

From the Coworld package root (`packages/coworld/src/coworld`):

```bash
uv run coworld play examples/paintarena/coworld_manifest.json
```

The command prints:

- one player client link per slot,
- a global viewer link,
- an admin link for pause, resume, and tick-rate controls,
- the local artifact directory for results, replay, and logs.

Open both player links before playing. The episode starts after both player websocket clients connect.

## Run A Local Episode

To run the full game with the bundled sweep-painter player image:

```bash
uv run coworld run-episode examples/paintarena/coworld_manifest.json coworld-paintarena:latest --run python --run -m --run coworld.examples.paintarena.player.player
```

This is the same local smoke-test shape a league player would use with their own image.

## Certify

From the Coworld package root (`packages/coworld/src/coworld`):

```bash
uv run coworld certify examples/paintarena/coworld_manifest.json
```

Certification runs the game and bundled sweep-painter policy containers end to end, then validates the results and replay
artifacts.

## View A Replay

After `play` or `certify` writes a replay artifact, start a replay viewer from the Coworld package root
(`packages/coworld/src/coworld`):

```bash
uv run coworld replay examples/paintarena/coworld_manifest.json path/to/replay.json
```

The command prints a replay client link and waits for the replay container to exit.

## Default Episode

The default variant is configured in `coworld_manifest.json`:

- `width`: 12
- `height`: 8
- `max_ticks`: 100
- `tick_rate`: 5

That makes the episode last about 20 seconds.
