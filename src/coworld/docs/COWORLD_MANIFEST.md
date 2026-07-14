# Coworld Manifest

Every Coworld package has a `coworld_manifest.json` file. The manifest is the package map: it tells Coworld tooling
which game to run, which bundled players and supporting runnables ship with the Coworld, which variants exist, which
docs are game-authored, and which certification episode proves the package works.

The field-level reference is the generated JSON Schema:

- [`coworld_manifest_schema.json`](../coworld_manifest_schema.json) is the canonical machine-readable contract.
- [`types.py`](../types.py) owns the Pydantic models and schema descriptions used to generate that JSON Schema.
- [`examples/paintarena/coworld_manifest_template.json`](../examples/paintarena/coworld_manifest_template.json) is the
  canonical worked example.

This document intentionally does **not** duplicate the schema field by field. It records how to use the manifest, which
semantics live outside normal JSON Schema, and where to look when authoring or changing manifests.

## Source Of Truth

The schema generated from `CoworldManifest` is the source of truth for:

- required and optional fields;
- object shapes;
- allowed role `type` values;
- defaulted arrays;
- `additionalProperties` behavior;
- the required `game.docs.readme` entry;
- role-documentation links through each role section's `x-coworld-role-doc` and `markdownDescription` metadata;
- minimum lengths and other directly expressible validation rules.

When a field contract changes, update the Pydantic model in [`types.py`](../types.py), regenerate the schema, and keep
this document focused on the surrounding semantics. Do not hand-edit `coworld_manifest_schema.json`.

## Role Sections

A complete Coworld conceptually has seven roles: game, player, commissioner, reporter, grader, diagnoser, and optimizer.
The schema currently enforces only the roles with stable required runtime contracts:

- `game` and `player` are required today.
- `commissioner`, `reporter`, `grader`, `diagnoser`, and `optimizer` are optional today.

The schema marks `diagnoser` and `optimizer` with descriptions plus `$comment` and `x-coworld-future-required: true`.
Use that metadata when building authoring tools or schema renderers; it is the machine-readable version of "not required
yet, but expected to be part of a complete Coworld."

The schema also links each role section back to its role contract using `x-coworld-role-doc` and a Markdown
`markdownDescription`. That round trip is intentional: someone reading `coworld_manifest_schema.json` cold should be
able to jump from `manifest.player[]` or `manifest.reporter[]` to the corresponding role doc.

For commissioner runnables, `id` is also the value used by `commissioner_config.commissioner_runnable_id` when a Coworld
league is seeded. That config key must match one `manifest.commissioner[].id`; the platform resolves the selected
runnable from the canonical Coworld manifest before starting the commissioner container.

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
3. Add reporter references when the Coworld ships bespoke reporting (reporter v2, spec 0061). Reporter entries are
   references — a platform reporter version (`"reporter": "owner/name@version"`, owner-qualified because reporter
   names are only unique per owner) or a wasm component your build produces (at publish time the CLI registers a
   reporter named `{coworld-name}-{reporter-id}` owned by you, then submits the component as a version against it) —
   not bundled container images. The section is optional and there are no default reporters. See the
   [Reporter role](roles/REPORTER.md).
4. Add grader runnables when the Coworld has custom graders or a default grader is useful.
5. Add commissioner, diagnoser, and optimizer runnables when the Coworld has custom implementations, or when a default
   image is appropriate for the role.
6. Define at least one variant.
7. Define the certification fixture that `coworld certify` and default local episode runs execute.
8. Validate locally before upload.

The exact field names, required fields, and nested object shapes belong to the schema. The manifest guide should stay at
this workflow level.

The first authenticated user upload for a Coworld `game.name` establishes that user as the name owner. Future uploads
for the same name must come from that original uploader or a Softmax team member.

## Game Configs, Tokens, And Player Names

`game.config_schema` is a JSON Schema for the runtime config the game reads from `COGAME_CONFIG_URI`. It must require a
string-array `tokens` field for runner-injected player auth. The token schema must declare `minItems` and `maxItems` so
non-commissioner flows can reject impossible rosters before launch. Those bounds are validity limits, not the
scheduler's chosen count: scheduled rosters, hosted-play requests, and certification players define the concrete player
slots.

Coworld-authored configs do **not** include `tokens`:

- `variants[].game_config` is token-free.
- `certification.game_config` is token-free.

The runner injects fresh tokens when it creates the concrete per-episode config. Authoring tools validate
author-provided configs by adding placeholder tokens first, not by expecting token values to appear in the manifest.

Games that need policy or player display names use `game_config.players[].name`, matching the Paint Arena example.

- Declare `game.config_schema.properties.players` as an array when the Coworld supports variable player counts or
  display names.
- If the game shows display names, each `players[]` item must be an object with required string field `name`.
- Hosted dispatch overwrites `game_config.players[].name` with resolved, per-slot display names when the schema declares
  the field.
- Local raw configs may set `players[].name` directly when a developer wants readable names without hosted dispatch.

Game-specific `slots` config objects remain game-owned and can carry mechanics such as roles, colors, spawn settings, or
other per-slot fields. Cross-Coworld player identity names flow through `game_config.players[].name`.

See [Game Role](roles/GAME.md#player-slots) and [Lifecycle](LIFECYCLE.md) for the runtime path.

## Hosted Episode Game Secrets

Manifest runnable `env` is public by default: uploaded manifests are visible to users, and downloaded Coworld packages
include the env values. Do not put raw API keys, signing keys, or cloud credentials directly in manifest env.

For hosted tournament and episode game-container secrets, upload the secret through the Coworld CLI and reference it
symbolically:

```bash
uv run coworld secret put cue_n_woo worker_signing_key ./tournament_signing_key.secret
```

```json
"env": {
  "WORKER_SIGNING_KEY_URI": "secret://coworld/cue_n_woo/worker_signing_key"
}
```

During hosted episode and replay-session dispatch, the backend resolves `secret://coworld/<coworld_name>/<secret_name>`
only for the matching Coworld and injects a short-lived presigned HTTPS URL into the game container env. Hosted replay
creation accepts only recorded replay URIs for that Coworld, and the stored Coworld owner, never the viewer, selects the
secret namespace. Hosted play and Antfarm dispatch do not resolve Coworld secrets; use the k8s hosted episode backend
for Coworlds whose game env contains `secret://` values.

Secrets are stored in the Coworld uploader's Coworld-name namespace. Passing a name to `coworld secret put` targets your
canonical Coworld for that name when you own it; pass the `cow_...` id to target a non-canonical candidate version
explicitly. Softmax team members must pass a `cow_...` id when a Coworld name maps to multiple owner namespaces.

Local users who run the downloaded game image see only the symbolic `secret://` URI and must override the env var with
their own local `file://`, HTTP(S), or other game-supported URI when they need a development secret.

Coworld secret uploads are capped at 1 MiB. Use them for credentials such as signing keys and tokens, not for large
datasets or model artifacts.

## Results Schema

`game.results_schema` validates the JSON object the game writes to `COGAME_RESULTS_URI`. Cross-game tooling expects the
results object to include a `scores` array with one numeric score per player slot. Game-specific result fields belong in
the Coworld's own `results_schema`.

See [Results Artifact](artifacts/RESULTS.md) for the artifact contract.

## Docs In The Manifest

The manifest stores document references, not local file uploads. A document is either inline text or a public HTTP(S)
URI. Referenced URI docs should be fetchable by users and tools after the Coworld is uploaded.

`game.docs.readme` is required and points to the Coworld's `README.md`. That README is the canonical game-authored
onboarding document for game rules, setup, player guidance, and context. It should be usable by humans and coding agents
after the Coworld is uploaded.

Game uploaders should put the durable game-owned material in `game.docs.readme`: rules, strategies, how to use or modify
a game-specific policy, and game-specific FAQs.

`game.docs.pages` is optional supplemental documentation. Coworlds may include pages for strategy notes, protocol
supplements, reference material, or legacy rule/play guides, but the manifest contract no longer requires a `rules.md`
or `play_*.md` page. When a Softmax league lists a `play_*.md` page, treat it as the platform play guide for Coworld CLI
setup, policy upload, league submission, placement matches, standings, logs, and replays rather than as game-owned
rules.

Protocol docs belong under `game.protocols`. If the game uses a shared protocol, point at the shared protocol document
instead of copying it into the game repo.

`game.protocols.engine_runtime` is an optional canonical engine family identifier, not a document URL. The supported
values are `mettagrid`, `cogweb`, `bitworld`, and `nimgrid`. Use `nimgrid` for Nim grid Coworlds such as the Tribal
games. `game.protocols.global` remains required; put supplemental runtime docs under `game.docs.pages`.

`game.promo` is optional promotional material. Its `video_url` is a public HTTP(S) URL for a promotional video. When
set, product UIs surface it: the Observatory league page shows a "Video Promo" tab that embeds the URL. Direct media
URLs (`.mp4`, `.webm`, …) render in a native player; other URLs (YouTube/Vimeo embeds, etc.) render in an iframe. Host
the file yourself on a public, embeddable URL; the manifest stores only the reference, never the bytes.

## Images, Runnables, And Releases

The manifest separates three concepts:

- **Container image:** uploaded Docker image bytes.
- **Runnable:** a role-specific invocation of an image with `type`, optional command, and public env.
- **Coworld release:** the manifest plus the images it references after upload.

One Docker image can implement multiple roles by appearing in multiple runnable entries with different `type` values or
different commands. `coworld upload-coworld` deduplicates image uploads by image reference and backend content identity.
At hosted execution time, image tags resolve to immutable digests.

`manifest.game.runnable.env.COWORLD_LOCAL_EXTRA_PORTS` is a local-runner-only deployment hint for games that expose
additional host TCP services beyond Coworld HTTP on container port 8080. Use comma-separated
`container_port[:host_port]` entries; `host_port` omitted or `0` means allocate a free localhost port. Local runners pass
the resolved mappings back into the game container as `COWORLD_LOCAL_PORT_<container_port>` and
`COWORLD_LOCAL_PORTS_JSON`. Hosted/Kubernetes runners do not support arbitrary extra host ports yet.

`source_url` is provenance for humans inspecting a runnable, not a runtime input: runners do not clone or execute code
from it. `coworld certify` checks GitHub URLs as a lightweight provenance test. A GitHub `source_url` may point at a
full commit SHA, a short SHA, a branch, a tag, or the bare repository URL. The source must resolve through GitHub's
contents API, have non-empty contents, and include a Dockerfile at that path or an ancestor build root. Full commit SHAs
are preferred because they make provenance stable, but mutable refs and bare repository URLs pass certification with a
warning because certification checked whatever the ref or default branch resolved to at run time. Point `source_url` at
the repository, directory, or file that implements the runnable, not just a documentation page. See
[REBUILDING_COWORLDS.md](REBUILDING_COWORLDS.md) for the current repo map and source-owner rules.

`repository_url` is an optional, machine-readable field used by `coworld optimize`: on an `optimizer[]` entry it names
the Git repository the command clones and runs locally (falling back to `Metta-AI/optimizers` when unset). Unlike
`source_url`, which may point at a subdirectory or file, `repository_url` must be the workbench repository root.

## Role Implementation Ownership

Coworld runtime ownership and role implementation ownership are separate:

- Metta/Coworld owns the manifest schema, runtime env vars, runner behavior, upload flow, and CLI.
- [`Metta-AI/coworld-tools`](https://github.com/Metta-AI/coworld-tools) owns imported shared implementations from the
  archived `players`, `commissioners`, `reporters`, `graders`, `diagnosers`, and `games` repositories. Treat it as the
  source library for reusable pieces and for starting a game-local copy.
- A `Metta-AI/coworld-<slug>` game repo owns game-local runnables that should move with that game.
- [`Metta-AI/optimizers`](https://github.com/Metta-AI/optimizers) remains the active optimizer workbench unless a
  specific optimizer has moved beside its game.

At episode or round runtime, the runner does not clone those repositories. It executes the image, command, and env
already recorded in the manifest. Catalogs are an authoring/provenance source: manifest authors copy the selected
implementation's `image` and `source_url` into the runnable, then `coworld build` pins the source ref when the matching
source context is provided.

Each runnable should have one source owner. The canonical workflow is to start from `packages/coworld` templates, the
Paint Arena example, or `coworld-tools`, then copy Coworld-specific code into the owning game repo and point the
manifest at that game-local source. Shared pieces point at `coworld-tools` only when the implementation is meant to
remain shared across Coworlds. Game-local starter players, game-specific commissioners, and in-tree examples point at
the game or package repo that owns them.

Backend storage, ECR publishing, public mirrors for bundled images, and private submitted-policy images are backend
mechanics; see [`COWORLD_MECHANICS.md`](../../../../../app_backend/src/metta/app_backend/v2/COWORLD_MECHANICS.md).

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
