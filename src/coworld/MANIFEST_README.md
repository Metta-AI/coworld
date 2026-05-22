# Coworld Manifest Reference

Every Coworld package has a `coworld_manifest.json` file that describes its game, players, supporting runnables,
variants, and certification fixture. This document is the field-by-field reference for that file.

For a complete worked example, see
[`worlds/paintarena/coworld_manifest_template.json`](../../../../worlds/paintarena/coworld_manifest_template.json).
For the canonical machine-readable schema, see [`coworld_manifest_schema.json`](coworld_manifest_schema.json).
For higher-level orientation, start with [`COWORLD_README.md`](COWORLD_README.md). For how the roles declared in this
manifest compose and what each one does, see [`docs/roles/OVERVIEW.md`](docs/roles/OVERVIEW.md).

## Top-Level Structure

A Coworld manifest is a JSON object with these top-level fields:

| Field          | Type                | Required? | Purpose                                                                                       |
| -------------- | ------------------- | --------- | --------------------------------------------------------------------------------------------- |
| `$schema`      | string              | no        | URI of the JSON Schema. Informational; consumed by IDEs.                                       |
| `game`         | object              | yes       | The game container, its protocols, schemas, and game-authored docs.                            |
| `player`       | array of runnables  | yes       | Bundled player images that can play the game. Must contain at least one entry.                 |
| `commissioner` | array of runnables  | yes       | Commissioner runnables. Must contain at least one entry; default available.                    |
| `reporter`     | array of runnables  | yes       | Reporter runnables. Must contain at least one entry; default available.                        |
| `grader`       | array of runnables  | yes       | Grader runnables. Must contain at least one entry; default available.                          |
| `diagnoser`    | array of runnables  | yes       | Diagnoser runnables. Must contain at least one entry; default available.                       |
| `optimizer`    | array of runnables  | yes       | Optimizer runnables. Must contain at least one entry; default available.                       |
| `variants`     | array of variants   | yes       | Named game configs (maps, difficulty levels, league settings, etc.). At least one entry.       |
| `certification`| object              | yes       | The short smoke-test episode used by `coworld certify` and `coworld run-episode`.              |

The manifest schema rejects unknown top-level fields. See
[`COWORLD_README.md` § Role Status](COWORLD_README.md#role-status) for which runnable arrays have a live platform
contract today and which currently rely on Softmax-published default images.

## Runnable Shape

Every runnable in the manifest — `game.runnable` and the seven array sections — shares a base shape:

| Field        | Type                 | Required? | Purpose                                                                          |
| ------------ | -------------------- | --------- | -------------------------------------------------------------------------------- |
| `type`       | string               | yes       | Role identifier; see [The `type` Field](#the-type-field) below.                  |
| `image`      | string               | yes       | Docker image reference. May be a build-time tag pre-publish, or a content-pinned reference post-publish. |
| `run`        | list of strings      | no        | Process command overriding the image's `ENTRYPOINT`/`CMD`. Omit to use the image default. |
| `env`        | map of string→string | no        | Public environment variables to set on the container. Secrets do not belong in the manifest; see the policy-upload flow in [`COWORLD_README.md`](COWORLD_README.md). |
| `source_url` | string               | no        | URL of the repository, directory, or file that builds this runnable. Informational; surfaced to humans inspecting the manifest. |

Array-role runnables — every entry in `player`, `commissioner`, `reporter`, `grader`, `diagnoser`, or `optimizer` —
add four more required fields:

| Field         | Type   | Required? | Purpose                                                                                            |
| ------------- | ------ | --------- | -------------------------------------------------------------------------------------------------- |
| `id`          | string | yes       | Stable identifier for this runnable within the manifest. Referenced by `certification.players[].player_id`. |
| `name`        | string | yes       | Human-readable display name shown in CLIs and UIs.                                                  |
| `description` | string | yes       | Short description of what this runnable does.                                                       |

The `game.runnable` object does not carry `id`, `name`, or `description` directly — that information lives one level
up on the `game` object itself (`game.name`, `game.description`, `game.owner`, `game.version`).

## The `type` Field

Every runnable declares which role contract it implements:

| Section in manifest | Required `type` value |
| ------------------- | --------------------- |
| `game.runnable`     | `"game"`              |
| `player[]`          | `"player"`            |
| `commissioner[]`    | `"commissioner"`      |
| `reporter[]`        | `"reporter"`          |
| `grader[]`          | `"grader"`            |
| `diagnoser[]`       | `"diagnoser"`         |
| `optimizer[]`       | `"optimizer"`         |

A runnable's `type` must match the section it appears under; the manifest schema rejects mismatches (an entry with
`"type": "reporter"` placed inside the `player` array fails validation).

`type` is redundant with the array name by design — it makes individual runnable objects self-describing when
extracted from the manifest, and it lets future tooling identify runnables without tracing the enclosing structure.

## Description Fields

`description` is required at three levels of the manifest: `game.description`, every entry in `variants[]`, and every
entry in each role-runnable array (`player[]`, `commissioner[]`, `reporter[]`, etc.). All three exist to be rendered.
`game.description` has known render surfaces today; the others are required so they are available when render
surfaces ship.

- `game.description` is surfaced on league cards and Coworld listing pages.
- `variants[].description` is intended for rendering wherever variants are presented — variant-selection UIs, CLI
  listings, league variant cards. The exact surfaces are still open.
- Each runnable's `description` (in `player[]`, `commissioner[]`, etc.) is intended for rendering wherever
  runnables are presented to humans. Concrete surfaces are not yet defined; expect role-catalog UIs and tools that
  enumerate the runnables a Coworld ships.

Authors should write each `description` as if it will be displayed to a human reader.

## `game` Section

The `game` object describes the game container and its surrounding metadata.

| Field             | Type                  | Required? | Purpose                                                                                |
| ----------------- | --------------------- | --------- | -------------------------------------------------------------------------------------- |
| `name`            | string                | yes       | Short Coworld name (e.g. `"paintarena"`, `"cogs_vs_clips"`).                            |
| `version`         | string (PEP 440)      | yes       | Coworld package version. Set at build time by `coworld build`; should not be checked in. |
| `description`     | string                | yes       | One-paragraph description of the game.                                                  |
| `owner`           | string                | yes       | Maintainer email or handle.                                                             |
| `config_schema`   | JSON Schema object    | yes       | Schema validating runtime game configs (variants + certification + runner-injected `tokens`). |
| `results_schema`  | JSON Schema object    | yes       | Schema validating the `results.json` artifact the game writes at episode end.            |
| `runnable`        | runnable object       | yes       | The game container — see [Runnable Shape](#runnable-shape). `type` must be `"game"`.    |
| `protocols`       | object                | yes       | Document references for the game's player and global websocket protocols (see below).   |
| `docs`            | object                | no        | Game-authored docs surfaced through the platform (see below).                           |

### `game.config_schema` requirements

`game.config_schema` is a JSON Schema defining the runtime game config. It must declare a required `tokens` field
that is a string array with equal `minItems` and `maxItems` — that fixed length is the number of player slots.
Coworld-authored configs (variants and `certification.game_config`) omit `tokens`; the runner injects fresh tokens
at episode start. See [`GAME_RUNTIME_README.md` § Player Slots](GAME_RUNTIME_README.md#player-slots) for the full
contract.

### `game.protocols`

```json
{
  "player": { "type": "uri", "value": "https://..." },
  "global": { "type": "uri", "value": "https://..." }
}
```

Both `player` and `global` are [Document Objects](#document-objects) referencing the game's player-websocket and
global-viewer-websocket protocol documentation.

### `game.docs`

```json
{
  "readme": { "type": "uri", "value": "https://..." },
  "pages": [ { "id": "...", "title": "...", "content": { "type": "uri", "value": "..." } }, ... ]
}
```

`readme` is an optional top-level doc. `pages` is a list of [Document Page](#document-pages) entries; see
[`game.docs.pages` Requirements](#gamedocspages-requirements) below.

## `variants` Section

Each variant names a specific game config (a "map" or "preset"):

| Field         | Type   | Required? | Purpose                                                                                  |
| ------------- | ------ | --------- | ---------------------------------------------------------------------------------------- |
| `id`          | string | yes       | Stable identifier referenced by `coworld play --variant <id>` and league configuration.  |
| `name`        | string | yes       | Human-readable display name.                                                              |
| `description` | string | yes       | One-paragraph description of the variant.                                                 |
| `game_config` | object | yes       | The game config to feed the game container. Must validate against `game.config_schema`. Must not include `tokens` — the runner injects them. |

## `certification` Section

The certification fixture is the short, deterministic episode that `coworld certify` and `coworld run-episode` (with
no override) execute to smoke-test the package end to end.

| Field         | Type             | Required? | Purpose                                                                              |
| ------------- | ---------------- | --------- | ------------------------------------------------------------------------------------ |
| `game_config` | object           | yes       | The config to feed the game container for the certification run. Must validate against `game.config_schema`. Token-free; runner injects. |
| `players`     | array of objects | yes       | Ordered per-slot player list. Length must equal the fixed `tokens` length from `game.config_schema`. |

Each entry in `players` has one field:

| Field       | Type   | Required? | Purpose                                                                       |
| ----------- | ------ | --------- | ----------------------------------------------------------------------------- |
| `player_id` | string | yes       | Must match the `id` of one of the entries in `manifest.player[]`. The same `player_id` may appear in multiple slots. |

## Document Objects

Many fields in the manifest accept a document reference rather than the document text itself. A document object is
either:

```json
{ "type": "uri", "value": "https://example.com/spec.md" }
```

or:

```json
{ "type": "text", "value": "Inline markdown content..." }
```

Use `type: "uri"` for public HTTP(S) URLs. Use `type: "text"` only when the docs are deliberately inlined in the
manifest (small notes; usually a `play_*.md` should be hosted on `softmax.com`).

Coworld upload stores the manifest as JSON. It does not bundle local Markdown files, schemas, or other assets, so
referenced URIs should be publicly fetchable.

## Document Pages

`game.docs.pages` entries are document pages, slightly richer than bare document objects:

| Field     | Type            | Required? | Purpose                                                       |
| --------- | --------------- | --------- | ------------------------------------------------------------- |
| `id`      | string          | yes       | Stable identifier (e.g. `"rules.md"`).                         |
| `title`   | string          | yes       | Display title (often matches `id`).                            |
| `content` | document object | yes       | The page content — see [Document Objects](#document-objects). |

### `game.docs.pages` Requirements

Every Coworld manifest must include at least two pages in `game.docs.pages`:

- `rules.md` — game-specific rules.
- A `play_*.md` page (e.g. `play_paintarena.md`, `play_cogsvsclips.md`) — the player-onboarding guide that league
  pages surface directly.

Additional pages (strategy notes, reference implementations, etc.) may be included as needed.

## See Also

- Worked example: [`worlds/paintarena/coworld_manifest_template.json`](../../../../worlds/paintarena/coworld_manifest_template.json).
- Canonical schema: [`coworld_manifest_schema.json`](coworld_manifest_schema.json).
- Roles system overview: [`docs/roles/OVERVIEW.md`](docs/roles/OVERVIEW.md) — the canonical home for how the roles
  compose, including the artifact flow diagram.
- Per-role contracts: [`docs/roles/`](docs/roles/) (game, player, commissioner, reporter, grader, diagnoser, optimizer).
- Game container runtime contract: [`GAME_RUNTIME_README.md`](GAME_RUNTIME_README.md).
- Episode bundle contract used by supporting runnables: [`EPISODE_BUNDLE_README.md`](EPISODE_BUNDLE_README.md).
