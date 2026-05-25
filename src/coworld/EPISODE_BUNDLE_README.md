# Episode Bundle

An **episode bundle** is a single `.zip` containing one Coworld episode's artifacts, assembled on demand for a
consumer that needs them as a unit. Bundles are the standard input format for supporting runnables — reporters,
graders, diagnosers, and optimizers — and for any CLI command that wants to operate on a full episode rather than
a single artifact.

Bundling is deliberately a **consumption-time** concern, not a production-time one. The runner writes individual
artifacts to separate URIs (see [KUBERNETES_RUNNER_README.md](runner/KUBERNETES_RUNNER_README.md) for hosted output
and [RUNNER_README.md](runner/RUNNER_README.md) for local output). Bundles are constructed only when a consumer
asks for one.

## Bundle Contents

A bundle is a zip containing some subset of the following entries plus a `manifest.json` describing what's present:

| Token         | File(s) in zip                                                                  | Source artifact                          |
| ------------- | ------------------------------------------------------------------------------- | ---------------------------------------- |
| `results`     | `results.json`                                                                  | `RESULTS_URI` / local `results.json`     |
| `replay`      | `replay.json` (uncompressed)                                                    | `REPLAY_URI` / local `replay`            |
| `config`      | `config.json`                                                                   | runner-written concrete game config      |
| `error_info`  | `error_info.json` (only present if the episode failed)                          | `ERROR_INFO_URI`                         |
| `game_logs`   | `logs/game.stdout.log`, `logs/game.stderr.log`                                  | inside `DEBUG_URI`'s zip / local `logs/` |
| `player_logs` | `logs/policy_agent_{slot}.log` (subject to access control — see below)          | `POLICY_LOG_URLS` / local `logs/`        |

The bundle stores `replay.json` uncompressed since the outer zip already compresses. The runner's local workspace
contains a single `replay` file with the exact bytes the game container wrote; the hosted upload path zlib-compresses
those bytes in memory at the upload boundary for hosted upload and replay-viewing paths that consume the compressed
form directly.

### `manifest.json`

Every bundle contains a `manifest.json` at the zip root describing its contents:

```json
{
  "ereq_id": "ereq_...",
  "status": "success",
  "include": ["results", "replay", "config", "game_logs", "player_logs"],
  "files": {
    "results": "results.json",
    "replay": "replay.json",
    "config": "config.json",
    "game_logs": {
      "stdout": "logs/game.stdout.log",
      "stderr": "logs/game.stderr.log"
    },
    "player_logs": {
      "0": "logs/policy_agent_0.log",
      "1": "logs/policy_agent_1.log"
    }
  }
}
```

- `status` is `"success"` or `"failed"`. On `"failed"`, `error_info.json` is typically present and most other files
  may be absent.
- `include` echoes the tokens that the bundle was built with, after access-control filtering.
- `files` maps each included token to its entry name(s) inside the zip. Consumers should read from `files` rather
  than hard-coding paths; the layout above is the current convention but may evolve.

## Requesting a Bundle

There are three surfaces; they share the same library code and produce identical bundles.

### CLI

```bash
uv run coworld bundle <ereq_id> --output ep.zip
uv run coworld bundle <ereq_id> --output ep.zip --include results,replay,config
```

Defaults to "everything the requester is permitted to see" when `--include` is omitted.

### Backend API

```
GET /v2/episodes/{ereq_id}/bundle?include=results,replay,player_logs
```

Returns a `.zip` body with `Content-Type: application/zip`. Auth uses the same model as the per-artifact endpoints
(`/v2/episodes/{ereq_id}/results`, `.../logs`, etc.). The `include` query parameter is comma-separated; omitting it
returns everything the requester is permitted to see.

### Library

```python
from coworld.bundle import build_episode_bundle, BundleSource

bundle_bytes = build_episode_bundle(
    source=BundleSource.local(workspace_path) | BundleSource.hosted(ereq_id),
    include=["results", "replay", "config"],  # omit for "everything permitted"
)
```

Used internally by the CLI and the backend API, and available for direct use by any in-process code that needs a
bundle (e.g. the CLI surface that invokes a local reporter).

## Access Control

The bundling layer applies the same per-artifact authorization model the existing artifact endpoints use, with one
additional rule for player logs:

- **`results`, `replay`, `config`, `error_info`, `game_logs`**: anyone with episode access can include them.
- **`player_logs`**: by default, the bundle includes only the logs for player slots controlled by policy versions
  the requester owns. Softmax-internal requesters may receive all player logs.

> **Game authors:** game container stdout and stderr are surfaced to *anyone* with episode access via the
> `game_logs` token. Do not write secrets, private credentials, or other confidential information to those streams.
> See [GAME_RUNTIME_README.md § Log visibility](GAME_RUNTIME_README.md#log-visibility).

If a requester asks for an `include` token they are not permitted to receive, the bundling layer silently omits
that token rather than failing the whole request. The returned `manifest.json`'s `include` field reflects what was
actually delivered.

## Consumption by Supporting Runnables

When the CLI or platform invokes a supporting runnable — reporter, grader, diagnoser, or optimizer — it first
assembles a bundle and then hands it to the runnable via:

```bash
COGAME_EPISODE_BUNDLE_URI=file:///path/to/bundle.zip
COGAME_EPISODE_BUNDLE_URI=https://.../ep.zip
```

The runnable reads the zip, inspects its `manifest.json` to discover what's inside, and processes the files. The
runnable does not need to know whether the bundle came from a local workspace or a hosted artifact store.

See [docs/roles/reporter.md](docs/roles/reporter.md), [docs/roles/grader.md](docs/roles/grader.md),
[docs/roles/diagnoser.md](docs/roles/diagnoser.md), and [docs/roles/optimizer.md](docs/roles/optimizer.md) for each
role's expected use of bundle contents.
