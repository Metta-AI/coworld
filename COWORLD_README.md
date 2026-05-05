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

### Reference Resolution

`game.manifest_uri` MUST resolve relative to the directory containing `coworld_manifest.json`. Paths inside the referenced
`cogame_manifest.json` MUST resolve relative to the directory containing that Cogame manifest.

Source manifests should use references rather than inlining Cogame manifests into Coworld manifests. If the platform needs
a single upload artifact, a bundling step can inline resolved files mechanically without changing the source format.


### Cogame

A Cogame is the game service referenced by `game.manifest_uri`. It validates against
[cogame_manifest_schema.json](cogame_manifest_schema.json) and defines the container runtime API, browser client routes,
websocket endpoints, config/results formats, and episode lifecycle described in [COGAME_README.md](COGAME_README.md).

### Player Client

The Cogame serves its player browser client from `GET /player?...`. A browser can request a link such as
`/player?slot=<slot>&token=<token>&initial_params=<value>` over HTTP and receive the player client.

By convention, the client reads the complete URL query string and forwards every query param when it opens the player
websocket on the same route, for example `ws://<engine-host>/player?slot=<slot>&token=<token>&initial_params=<value>`.

### Global Client

The Cogame serves its global browser client from `GET /global`. A browser can request `/global` over HTTP and receive
the global client.

By convention, the client reads the complete URL query string and forwards every query param when it opens the global
websocket on the same route, for example `ws://<engine-host>/global`.

### Player

A base player policy competently plays the game. See [COGAME_README.md](COGAME_README.md) for how a player should be
implemented.

### Certification Fixture

A short deterministic smoke episode proves that the Coworld works end to end.

```json
{
  "certification": {
    "variant_id": "default",
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

A graph of game configurations, each of which adheres to the game's config schema. It factorizes the game into mechanics,
so walking the tree generates experience targeted at learning different aspects of the game independently for training
purposes.

## Play

To start a local game for browser play:

```bash
uv run coworld play path/to/coworld_manifest.json
```

The command uses the certification fixture for game config and player slots, then prints player and global client links.
Each link points directly at the Cogame's HTTP client route. The served client forwards the link's query params when it
connects back to the Cogame over websocket.

## Certification

Coworld certification resolves the fixture into an `EpisodeInput` from
[episode_request_schema.json](episode_request_schema.json), supplies artifact destinations, and runs the Cogame lifecycle
described in [COGAME_README.md](COGAME_README.md).

Operational details:

- The certifier does not build images; referenced images must already be available locally or in a reachable registry.
- Local images are checked with `docker image inspect`; remote images are checked with `docker manifest inspect`.
- Private registries such as GHCR or ECR require the local Docker client to be logged in first.
- Successful runs print artifact, result, replay, and log paths under `tmp/coworld-cert-*`.

Certification validates the Coworld and Cogame manifests, checks referenced files and images, verifies the Cogame serves
its player and global browser clients in rollout mode, verifies the Cogame serves its replay browser client in replay
mode, runs one smoke episode through Docker, and verifies the produced results and replay artifacts.
