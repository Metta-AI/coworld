# Paint Arena Coworld Example

Paint Arena is a two-player tick-based Coworld example. Each player moves around the grid and paints the tile they are
standing on. Painting overwrites the previous owner, and final scores are the number of tiles painted with each player's
color.

## Build Images

From this directory:

```bash
docker build -t coworld-paintarena-game:latest game
docker build -t coworld-paintarena-player:latest player
```

From the Coworld package root (`packages/coworld`):

```bash
docker build -t coworld-paintarena-game:latest examples/paintarena/game
docker build -t coworld-paintarena-player:latest examples/paintarena/player
```

## Play Locally

From the Coworld package root (`packages/coworld`):

```bash
uv run coworld play examples/paintarena/coworld_manifest.json
```

The command prints:

- one player client link per slot,
- a global viewer link,
- an admin link for pause, resume, and tick-rate controls,
- the local artifact directory for results, replay, and logs.

Open both player links before playing. The episode starts after both player websocket clients connect.

## Certify

From the Coworld package root (`packages/coworld`):

```bash
uv run coworld certify examples/paintarena/coworld_manifest.json
```

Certification runs the game and bundled sweep-painter policy containers end to end, then validates the results and replay
artifacts.

## View A Replay

After `play` or `certify` writes a replay artifact, start a replay viewer from the Coworld package root
(`packages/coworld`):

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
