# Coworld Specification

A coworld is a set of docker images and configurations that form a game ecosystem in the Softmax universe.

A viable coworld is one that has enough integration points implemented in a compliant way that Softmax can make use of it.


## Coworld Package Specification

A viable coworld package provides a `coworld_manifest.json` at its root that adheres to
[coworld_manifest_schema.json](coworld_manifest_schema.json) and passes certification:

```bash
uv run coworld certify path/to/coworld_manifest.json
```

The schema provides a full description for what it requires. A summary of the required elements:

- [Cogame](#cogame)
- [Certification fixture](#certification-fixture)
- [Player](#player)
- [Variants](#variants)

Currently optional elements that will soon be required:

- [Grader](#grader)
- [Reporter](#reporter)
- [Commissioner](#commissioner)
- [Diagnoser](#diagnoser)
- [Optimizer](#optimizer)

For a complete small implementation, see [examples/paintarena/](examples/paintarena/).

### Protocol Documentation

`game.protocols.player` and `game.protocols.global` are explicit document objects:

```json
{ "type": "uri", "value": "https://example.com/player_protocol.md" }
```

Use `type: "uri"` for absolute HTTP(S) links, or `type: "text"` for deliberately inline documentation text. Upload does
not infer local file paths or inline local protocol documentation into the stored manifest.

### Cogame

A Cogame is the game service declared by the inline `game` object in `coworld_manifest.json`. It defines the container
runtime API, browser client routes, websocket endpoints, config/results formats, and episode lifecycle described in
[COGAME_README.md](COGAME_README.md).

### Player Client

The Cogame serves its player browser client from `GET /clients/player?...`. A browser can request a link such as
`/clients/player?slot=<slot>&token=<token>&role=<value>` over HTTP and receive the player client.

By convention, the client reads the complete URL query string and forwards every query param when it opens the player
websocket route, for example `ws://<engine-host>/player?slot=<slot>&token=<token>&role=<value>`.

### Global Client

The Cogame serves its global browser client from `GET /clients/global`. A browser can request `/clients/global` over
HTTP and receive the global client.

By convention, the client reads the complete URL query string and forwards every query param when it opens the global
websocket route, for example `ws://<engine-host>/global`.

### Player

A base player policy competently plays the game. See [COGAME_README.md](COGAME_README.md) for how a player should be
implemented.

The game, player, grader, reporter, commissioner, diagnoser, and optimizer entries are runnables. A runnable names a
container image plus an optional complete `run` argv and public `env`, so one image can implement multiple Coworld roles
with different commands.

### Certification Fixture

A short deterministic smoke episode proves that the Coworld works end to end.

```json
{
  "certification": {
    "game_config": {
      "map": "default"
    },
    "players": [
      { "player_id": "first-empty-player" },
      { "player_id": "first-empty-player" }
    ]
  }
}
```

### Grader

An executable that attaches to the `/global` stream on a game and outputs a scalar reflecting game quality.

_Contract to be specified._

### Reporter

An executable that attaches to the `/global` stream and emits text about important or interesting game events.

_Contract to be specified._

### Commissioner

An executable that runs tournaments for the game and produces valid rankings.

_Contract to be specified._

### Diagnoser

An executable that takes a player as input, runs targeted episodes, and uses the `/global` stream or episode outputs to
assess player competence.

_Contract to be specified._

### Optimizer

An executable that improves the player and grader. This is often a documentation file or coding-agent image that
describes how the player and grader work.

_Contract to be specified._

### Variants

A graph of token-free game configurations. Variants factorize the game into mechanics, so walking the tree generates
experience targeted at learning different aspects of the game independently for training purposes.

Each `variants[].game_config` is author-owned game data and must omit runner-managed `tokens`. Certification validates
each variant by injecting dummy tokens of the exact fixed length declared by `game.config_schema.properties.tokens`, then
checking the derived playable config against the game's config schema.

## Play

To start a local game for browser play:

```bash
uv run coworld play path/to/coworld_manifest.json
uv run coworld play https://softmax.com/api/v2/coworlds/cow_...
uv run coworld play /v2/coworlds/cow_... --server https://softmax.com/api
```

The `play`, `replay`, and `certify` commands accept local paths, full HTTP(S) manifest URIs, backend
`/v2/coworlds/cow_...` paths with `--server`. The command downloads URI manifests to a temporary local file, uses the
certification fixture for game config and player slots, then prints player and global client links.
Observatory's public Coworld manifest endpoint returns public image URIs for Softmax-managed images once those images
have been mirrored to public ECR.
Each link points directly at the Cogame's HTTP client route. The served client forwards the link's query params when it
connects back to the Cogame over websocket.

## Certification

Coworld certification resolves the fixture into an `EpisodeInput` from
[runner/episode_request_schema.json](runner/episode_request_schema.json), supplies artifact destinations, and runs the
Cogame lifecycle described in [COGAME_README.md](COGAME_README.md).

Operational details:

- The certifier does not build images; referenced images must already be available locally or in a reachable registry.
- Local images are checked with `docker image inspect`; remote images are checked with `docker manifest inspect`.
- Private registries such as GHCR or ECR require the local Docker client to be logged in first.
- Successful runs print artifact, result, replay, and log paths under `tmp/coworld-cert-*`.

Certification validates the Coworld manifest, checks referenced images, verifies the Cogame serves its player and global
browser clients in rollout mode, verifies the Cogame serves its replay browser client in replay mode, runs one smoke
episode through Docker, and verifies the produced results and replay artifacts.

Manifest validation requires `game.config_schema` to define `tokens` as a required string array with equal `minItems` and
`maxItems`. The certification fixture's player count must match that fixed token count.

## Upload

To certify and upload a Coworld manifest to the CoGames platform:

```bash
uv run coworld upload-coworld path/to/coworld_manifest.json
```

To inspect uploaded Coworlds and uploaded runnable images:

```bash
uv run coworld list
uv run coworld show cow_...
uv run coworld images
uv run coworld images img_...
```

The Coworld upload command validates the manifest, runs certification, uploads every runnable image through the platform's
`/v2/container_images/upload` flow, rewrites runnable image references to returned Softmax digest image URIs, and uploads
the resulting standalone JSON manifest through `/v2/coworlds/upload`. Protocol documentation objects remain unchanged in
the uploaded manifest.

Upload does not bundle schemas, docs, or other package files. The manifest is the uploaded artifact. Documentation and
other supporting references should be publicly accessible links. The current uploader does not validate those links.

The uploader derives an optional client hash from the local image archive's config and layer content, uses it to skip
re-uploading images the platform already has, and records ECR's digest as the executable image identity:

```bash
docker build --platform=linux/amd64 -t my-coworld-runtime:latest .
```

Production Coworld jobs run on linux/amd64 Kubernetes nodes. Build local images for `linux/amd64` before uploading,
especially from Apple Silicon machines.

To upload a Coworld policy image and enter it into a league:

```bash
uv run coworld upload-policy my-policy-image:latest --name my-policy
uv run coworld submit my-policy --league league_...
uv run coworld submit my-policy:v2 --league league_...
```

## Download

To download a published Coworld manifest and retag its public images for local development:

```bash
uv run coworld download cow_...
```

The command fetches the public manifest, pulls each referenced public image, writes a local `coworld_manifest.json`, and
writes `coworld_images.json` with the public-to-local image tag mapping.
