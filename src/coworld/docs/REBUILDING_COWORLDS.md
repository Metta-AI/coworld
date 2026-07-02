# Rebuilding Coworlds After The Role Repo Move

This guide is for rebuilding or fixing an existing Coworld after the June 2026 repository consolidation.

## Current Source Map

- `packages/coworld` contains the public Coworld package, starter templates under
  [`templates`](../templates/README.md), and the complete [Paint Arena example](../examples/paintarena/README.md).
- [`Metta-AI/coworld-tools`](https://github.com/Metta-AI/coworld-tools) contains the imported shared implementation
  trees from the old `players`, `commissioners`, `reporters`, `graders`, `diagnosers`, and `games` repositories. Those
  old role repos are archived pointers now; do not start new work there.
- A `Metta-AI/coworld-<slug>` game repo owns game-specific pieces that only make sense for that game: the game server,
  bundled starter players, local reporters or graders, and any commissioner that is intentionally coupled to that game.
- `Metta-AI/optimizers` is still the active optimizer workbench repository unless a specific optimizer has moved beside
  its game.

## Canonical Flow

When you build or repair a Coworld piece, start from one of the shared sources:

- copy a role template from `packages/coworld/src/coworld/templates`;
- copy the matching role from the Paint Arena example under `packages/coworld/src/coworld/examples/paintarena`; or
- copy the closest existing implementation from `Metta-AI/coworld-tools`.

Then put the Coworld-specific copy in the owning game repo, for example `Metta-AI/coworld-muster/commissioner/`,
`Metta-AI/coworld-muster/reporter/`, or `Metta-AI/coworld-muster/players/<starter>/`. Update that game repo's
`compose.yaml` and `coworld_manifest.json` so the runnable builds from the game-local folder and its `source_url` points
at the game repo.

Use `coworld-tools` directly only when the runnable is intentionally shared and should change for every Coworld that
uses it. Most fixes for "the commissioner for this Coworld" are not shared fixes; copy from `coworld-tools` or the
template into the game repo first, then modify the game-local copy.

## The One-Owner Rule

Each runnable in a release manifest must point to exactly one source owner:

- **Shared role implementation:** leave it in `coworld-tools` only when it is meant to stay shared, and use a
  `source_url` like
  `https://github.com/Metta-AI/coworld-tools/tree/<sha>/commissioners/commissioners/ruleset_strategy_commissioner`.
- **Game-local implementation:** keep it beside the game and use a `source_url` like
  `https://github.com/Metta-AI/coworld-crewrift/tree/<sha>/commissioner`.
- **Package example or template:** keep it in the Coworld package and use a `source_url` under
  `https://github.com/Metta-AI/coworld/tree/<sha>/src/coworld/...`.

Do not point new manifests at archived repos such as `Metta-AI/commissioners`, `Metta-AI/reporters`,
`Metta-AI/graders`, `Metta-AI/diagnosers`, or `Metta-AI/players`. Do not leave the same runnable split between
`coworld-tools` and a game repo; choose one owner before rebuilding.

## Rebuild Workflow

1. Identify every runnable in the manifest: `game`, `player`, `commissioner`, `reporter`, `grader`, `diagnoser`, and
   `optimizer`.
2. Choose the source owner for each runnable. The default for a Coworld-specific piece is the game repo. Start from
   `packages/coworld` templates, Paint Arena, or `coworld-tools`, then copy the relevant piece into the game repo before
   customizing it.
3. Edit the chosen owner repo and build from that checkout. Use `coworld-tools` as the owner only for pieces that are
   deliberately shared across Coworlds.
4. Make the manifest `source_url` match the chosen owner. Release manifests should prefer full commit SHAs for stable
   provenance. Manifest templates may use a branch ref, short SHA, tag, or bare repository URL; certification accepts
   those mutable refs with a warning after checking the GitHub source at run time.
5. Rebuild with all relevant source contexts:

   ```bash
   uv run coworld build \
     --source-context ../coworld-tools \
     --source-context ../coworld-crewrift \
     worlds/crewrift/compose.yaml \
     ../coworld-crewrift/coworld_manifest.json \
     0.1.60 \
     tmp/crewrift/coworld_manifest.json
   ```

6. Certify and upload the hydrated manifest:

   ```bash
   uv run coworld certify tmp/crewrift/coworld_manifest.json
   uv run coworld upload-coworld tmp/crewrift/coworld_manifest.json
   ```

The Metta `worlds/upload.sh` helper follows the same rule: game contexts point at `coworld-*` repos, shared role
contexts point into `coworld-tools`, and optimizer contexts point at `optimizers` unless explicitly overridden.

## Commissioner Changes

For commissioners, decide whether you are changing a shared tournament strategy or a game-specific league controller.

- If the Coworld uses the reusable `ruleset_strategy` commissioner unchanged, keep the source in
  `coworld-tools/commissioners/commissioners/ruleset_strategy_commissioner`.
- If you are changing a bundled YAML config that should remain shared across games, edit that config in
  `coworld-tools`.
- If you are fixing the commissioner for one Coworld, copy the closest starter from
  `packages/coworld/src/coworld/templates/roles/commissioner`, Paint Arena, or `coworld-tools/commissioners` into a
  game-local folder such as `coworld-muster/commissioner/`. Update the Coworld compose file to build that image, and
  point `manifest.commissioner[].source_url` at the game repo. For example, a Crewrift-specific commissioner belongs in
  `Metta-AI/coworld-crewrift`, not in the archived `Metta-AI/commissioners` repo.

The platform does not read commissioner behavior from the database at runtime. It runs the commissioner image selected
by the uploaded Coworld manifest.
