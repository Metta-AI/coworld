# Coworld Manifest

Every Coworld package has a `coworld_manifest.json` file. The manifest is the package map: it tells Coworld tooling which
game to run, which bundled players and supporting runnables ship with the Coworld, which variants exist, which docs are
game-authored, and which certification episode proves the package works.

The field-level reference is the generated JSON Schema:

- [`coworld_manifest_schema.json`](../coworld_manifest_schema.json) is the canonical machine-readable contract.
- [`types.py`](../types.py) owns the Pydantic models and schema descriptions used to generate that JSON Schema.
- [`examples/paintarena/coworld_manifest_template.json`](../examples/paintarena/coworld_manifest_template.json)
  is the canonical worked example.

This document intentionally does **not** duplicate the schema field by field. It records how to use the manifest, which
semantics live outside normal JSON Schema, and where to look when authoring or changing manifests.

## Source Of Truth

The schema generated from `CoworldManifest` is the source of truth for:

- required and optional fields;
- object shapes;
- allowed role `type` values;
- defaulted arrays;
- `additionalProperties` behavior;
- required `game.docs.pages` entries;
- role-documentation links through each role section's `x-coworld-role-doc` and `markdownDescription` metadata;
- minimum lengths and other directly expressible validation rules.

When a field contract changes, update the Pydantic model in [`types.py`](../types.py), regenerate the schema, and keep
this document focused on the surrounding semantics. Do not hand-edit `coworld_manifest_schema.json`.

## Role Sections

A complete Coworld conceptually has seven roles: game, player, commissioner, reporter, grader, diagnoser, and optimizer.
The schema currently enforces only the roles with stable required runtime contracts:

- `game`, `player`, and `reporter` are required today.
- `commissioner`, `grader`, `diagnoser`, and `optimizer` are optional today but intended to become required as their
  contracts stabilize.

`coworld upload-coworld` and the backend Coworld upload endpoint are stricter than the base schema: new uploads must
include at least one `grader[]` runnable. The base schema still accepts missing or empty `grader` arrays so historical
Coworld rows, downloads, and read-only tooling do not need a backfill before they can be loaded.

The schema marks those future-required role arrays with descriptions plus `$comment` and
`x-coworld-future-required: true`. Use that metadata when building authoring tools or schema renderers; it is the
machine-readable version of "not required yet, but expected to be part of a complete Coworld."

The schema also links each role section back to its role contract using `x-coworld-role-doc` and a Markdown
`markdownDescription`. That round trip is intentional: someone reading `coworld_manifest_schema.json` cold should be
able to jump from `manifest.player[]` or `manifest.reporter[]` to the corresponding role doc.

For role semantics, use the role docs rather than the schema:

- [Game](roles/GAME.md)
- [Player](roles/PLAYER.md)
- [Commissioner](roles/COMMISSIONER.md)
- [Reporter](roles/REPORTER.md)
- [Grader](roles/GRADER.md)
- [Diagnoser](roles/DIAGNOSER.md)
- [Optimizer](roles/OPTIMIZER.md)

## Authoring Workflow

For a new Coworld, start from the Paint Arena manifest template and keep the generated schema open in your editor:

1. Fill in `game` metadata, docs, protocols, config schema, results schema, and game runnable.
2. Add bundled players used for examples, certification, and local play.
3. Add reporter runnables, using the default reporter image when the Coworld does not yet have a custom one.
4. Add a grader runnable. Use the default grader image when the Coworld does not yet have a custom grader.
5. Add commissioner, diagnoser, and optimizer runnables when the Coworld has custom implementations, or when a default
   image is appropriate for the role.
6. Define at least one variant.
7. Define the certification fixture that `coworld certify` and default local episode runs execute.
8. Validate locally before upload.

The exact field names, required fields, and nested object shapes belong to the schema. The manifest guide should stay at
this workflow level.

## Game Configs And Runner-Injected Tokens

`game.config_schema` is a JSON Schema for the runtime config the game reads from `COGAME_CONFIG_URI`. It has one
cross-Coworld requirement that is easier to explain here than in a field table: it must require a fixed-length
string-array `tokens` field. The fixed length defines the player slot count.

Coworld-authored configs do **not** include `tokens`:

- `variants[].game_config` is token-free.
- `certification.game_config` is token-free.

The runner injects fresh tokens when it creates the concrete per-episode config. That means authoring tools should
validate the author-provided configs by adding placeholder tokens first, not by expecting tokens to appear in the
manifest.

See [Game Role](roles/GAME.md#player-slots) and [Lifecycle](LIFECYCLE.md) for the runtime path.

## Results Schema

`game.results_schema` validates the JSON object the game writes to `COGAME_RESULTS_URI`. Cross-game tooling expects the
results object to include a `scores` array with one numeric score per player slot. Game-specific result fields belong in
the Coworld's own `results_schema`.

See [Results Artifact](artifacts/RESULTS.md) for the artifact contract.

## Docs In The Manifest

The manifest stores document references, not local file uploads. A document is either inline text or a public HTTP(S)
URI. Referenced URI docs should be fetchable by users and tools after the Coworld is uploaded.

`game.docs.pages` must include:

- exactly one `rules.md` page;
- exactly one `play_*.md` page whose id matches `^play_[a-z0-9][a-z0-9_-]*\.md$`.

The `rules.md` page explains the game. The `play_*.md` page is the player-onboarding guide surfaced by player-facing
flows. Additional game-authored pages can be included for strategy notes, protocol supplements, or reference material.

## Images, Runnables, And Releases

The manifest separates three concepts:

- **Container image:** uploaded Docker image bytes.
- **Runnable:** a role-specific invocation of an image with `type`, optional command, and public env.
- **Coworld release:** the manifest plus the images it references after upload.

One Docker image can implement multiple roles by appearing in multiple runnable entries with different `type` values or
different commands. `coworld upload-coworld` deduplicates image uploads by image reference and backend content identity.
At hosted execution time, image tags resolve to immutable digests.

`source_url` is informational for humans inspecting a runnable, but `coworld certify` also checks GitHub URLs for
non-empty contents and a Dockerfile at that path or an ancestor build root. Point it at the repository, directory, or
file that implements the runnable, not just a documentation page.

`repository_url` is an optional, machine-readable field used by `coworld optimize`: on an `optimizer[]` entry it names
the Git repository the command clones and runs locally (falling back to `Metta-AI/optimizers` when unset). Unlike
`source_url`, which may point at a subdirectory or file, `repository_url` must be the workbench repository root.

Backend storage, ECR publishing, public mirrors for bundled images, and private submitted-policy images are backend
mechanics; see
[`COWORLD_MECHANICS.md`](../../../../../app_backend/src/metta/app_backend/v2/COWORLD_MECHANICS.md).

## Validation And Regeneration

The normal validation path is:

```bash
uv run --project packages/coworld python packages/coworld/scripts/generate_coworld_schemas.py
uv run --project packages/coworld pytest packages/coworld/tests/test_types.py
```

The first command regenerates:

- `packages/coworld/src/coworld/coworld_manifest_schema.json`
- `packages/coworld/src/coworld/runner/episode_request_schema.json`

The tests validate important schema behavior and include a guard that every generated manifest-model field carries a
description. That guard is there to keep the schema self-documenting enough that Markdown does not need to restate every
field.

## See Also

- [Coworld overview](README.md) for the role model and artifact flow.
- [Lifecycle](LIFECYCLE.md) for local and hosted episode execution.
- [Artifact reference](artifacts/README.md) for outputs produced from manifest-defined roles.
- [Cookbook](../../../COOKBOOK.md) for local play, certification, upload, and inspection recipes.
