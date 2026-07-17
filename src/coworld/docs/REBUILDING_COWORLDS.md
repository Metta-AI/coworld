# Rebuilding Coworlds

Each Coworld project owns its release inputs:

- `compose.yaml` describes every container image used by the manifest;
- `coworld_manifest_template.json` describes the game and its roles without `game.version`;
- `dist/coworld_manifest.json` is generated and must not be committed.

Keep game-specific game, player, commissioner, grader, diagnoser, and optimizer implementations in the game project.
Use a shared role image only when it is intentionally shared and should change for every Coworld that consumes it.
Reporter entries are platform or wasm references, not container services.

## Build Workflow

From the owning project root:

```bash
uv run coworld build --version 0.1.0
uv run coworld certify dist/coworld_manifest.json
uv run coworld upload-coworld dist/coworld_manifest.json
```

`coworld build` pulls and builds the compose services, resolves every mutable image reference to a digest, substitutes
the image placeholders, stamps the requested version, and validates the result. It also pins mutable GitHub
`source_url` values that belong to the current Git checkout to the checkout's commit. Build from committed, pushed
state so those source commits are available to certification and future rebuilds.

For a nonstandard layout, select the project and override individual filenames only when needed:

```bash
uv run coworld build --project path/to/coworld --version 0.1.0
```

Do not create a second compose file or manifest template in a coordinating repository. Fix and release the files in
the repository that owns the Coworld.

## One-Owner Rule

Every runnable has one source owner. Its `source_url`, Docker build context, and implementation must agree. A shared
implementation may remain in a shared role repository; a game-specific change belongs beside the game. Never split a
runnable between an orchestration checkout and its game project.
