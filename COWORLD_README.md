# Coworld Specification

A coworld is a set of docker images and configurations that form a game ecosystem in the Softmax universe.

A viable coworld is one that has enough integration points implemented in a compliant way that Softmax can make use of it.

Coworlds that provide a complete manifest -- one that matches
[coworld_manifest_schema.json](coworld_manifest_schema.json) -- meet this bar.

## Package Specification

A coworld implementation is delivered in a coworld package format. It describes the game as a thing that can be played,
trained, evaluated, inspected, improved, and run as a tournament inside the Softmax universe. It contains a
`coworld_manifest.json` file that specifies, relative to the package, locations for the required entities.

The Cogame manifest is a separate file referenced by `game.manifest_uri`. This keeps the game service independently
validatable while allowing the Coworld to compose that game with players, variants, and certification inputs.

Entities:

- the cogame (a reference to a Cogame manifest)
- the player client (a static browser client for connecting to one player slot)
- the global client (a static browser client for watching or replaying the whole episode)
- the player (one or more executables that play the game competently)
- the grader (one or more executables for estimating expected score or probability of winning)
- the reporter (one or more executables for summarizing game experience)
- the commissioner (one or more executables for running tournaments and producing rankings)
- the diagnoser (one or more executables for assessing basic competence across important situations)
- the optimizer (one or more executables or agents for improving players and graders)
- the variants (a tree of game configs targeted at mechanics, training, evaluation, and curriculum design)
- the certification fixture (the smoke episode the platform certifier runs)

## Reference Resolution

`game.manifest_uri` MUST resolve relative to the directory containing `coworld_manifest.json`. Paths inside the referenced
`cogame_manifest.json` MUST resolve relative to the directory containing that Cogame manifest.
`clients.player` and `clients.global` MUST resolve relative to the directory containing `coworld_manifest.json`.

Source manifests should use references rather than inlining Cogame manifests into Coworld manifests. If the platform needs
a single upload artifact, a bundling step can inline resolved files mechanically without changing the source format.

## Certification

Coworld certification is the platform smoke test for a Coworld. The `certification` block uses the `EpisodeInput` shape
from [episode_request_schema.json](episode_request_schema.json); the certifier supplies artifact destinations and runs the
Cogame lifecycle described in [COGAME_README.md](COGAME_README.md).

To run certification locally:

```bash
uv run --package coworld coworld certify path/to/coworld_manifest.json
```

Facts to know:

- The certifier does not build images; referenced images must already be available locally or in a reachable registry.
- Local images are checked with `docker image inspect`; remote images are checked with `docker manifest inspect`.
- Private registries such as GHCR or ECR require the local Docker client to be logged in first.
- Successful runs print artifact, result, replay, and log paths under `tmp/coworld-cert-*`.

Certification validates the Coworld and Cogame manifests, checks referenced files and images, runs one smoke episode
through Docker, and verifies the produced results and replay artifacts.

## Details

- the game: there must be a game referenced by `game.manifest_uri` that validates against
  [cogame_manifest_schema.json](cogame_manifest_schema.json). For the core Cogame manifest, container runtime API,
  websocket endpoints, config/results formats, and episode lifecycle, see [COGAME_README.md](COGAME_README.md).
- The player client: there must be a static browser client at `clients.player` that connects to one player slot.
- The global client: there must be a static browser client at `clients.global` that watches live episodes and replays.
- The player: there must be a base player policy that can competently play the game. See [COGAME_README.md](COGAME_README.md) for how a player should be implemented.
- The grader: there must be a base grader policy that can predict expected probability of winning, or score if the game
  does not have win/loss, during the course of a game for a player.
- The reporter: there must be a base reporter policy that knows how to summarize the logs from game experience into high
  level descriptions of the important events of the game.
- The commissioner: there must be a base commissioner policy that can competently run a tournament for the game, such
  that a valid ranking can be established.
- The diagnoser: there must be a valid set of diagnostic policies or tests, such that players can be assessed for basic
  competence in all mechanics and situations that arise in normal gameplay.
- The optimizer: there must be a base optimizer policy that can be used to make improvements to the player and grader.
  This is often a documentation file or coding-agent image that describes how the player and grader work.
- The variants: there must be some factorization of the game into mechanics that can be used to generate experience
  targeted at learning various aspects of the game independently for training purposes.
- The certification fixture: there must be one short deterministic episode input that the platform can run to prove the
  Coworld works end to end.
