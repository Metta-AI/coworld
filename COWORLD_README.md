# Coworld

A coworld is what is needed to be a complete game world in the Softmax universe. It contains:

- One Cogame, referenced by `game.manifest_uri`. The referenced manifest is a `cogame_manifest.json` that validates
  against [cogame_manifest_schema.json](cogame_manifest_schema.json). For the core Cogame manifest, container runtime
  API, websocket endpoints, config/results formats, browser client requirements, and episode lifecycle, see
  [COGAME_README.md](COGAME_README.md).
- Zero or more players.
- Zero or more graders.
- Zero or more reporters.

Variants are optional game configs that locate themselves in a tree.

`coworld_manifest_schema.json` defines the coworld manifest schema for higher-level Cogame integrations.
