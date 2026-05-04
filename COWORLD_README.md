# Coworld Specification

A coworld is a set of docker images and configurations that form a game ecosystem in the Softmax universe.

A viable coworld is one that has enough integration points implemented in a compliant way that Softmax can make use of it.

Coworlds that provide a complete manifest -- one that matches [cogame_manifest_schema.json](cogame_manifest_schema.json) -- meet this bar.

## Package Specification

A coworld implementation is delivered in a coworld package format. It describes the game as a thing that can be played,
trained, evaluated, inspected, improved, and run as a tournament inside the Softmax universe. It contains a manifest
which specifies, relative to the package, locations for the required entities.

Entities:

- the cogame (a reference to a Cogame manifest)
- the player (one or more executables that play the game competently)
- the grader (one or more executables for estimating expected score or probability of winning)
- the reporter (one or more executables for summarizing game experience)
- the commissioner (one or more executables for running tournaments and producing rankings)
- the diagnoser (one or more executables for assessing basic competence across important situations)
- the optimizer (one or more executables or agents for improving players and graders)
- the variants (a tree of game configs targeted at mechanics, training, evaluation, and curriculum design)


## Details

- the game: there must be a game referenced by `game.manifest_uri` that validates against
  [cogame_manifest_schema.json](cogame_manifest_schema.json). For the core Cogame manifest, container runtime API,
  websocket endpoints, config/results formats, browser client requirements, and episode lifecycle, see [COGAME_README.md](COGAME_README.md).
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
