# Episode Bundle

An **episode bundle** is a single `.zip` containing one Coworld episode's artifacts, assembled on demand for a consumer
that needs them as a unit. Bundles are the intended standard input format for supporting runnables — reporters, graders,
diagnosers, and optimizers — and for future tools that need to operate on a full episode rather than a single artifact.

Bundling is deliberately a **consumption-time** concern, not a production-time one. The runner writes individual
artifacts to separate URIs (see [KUBERNETES_RUNNER_README.md](../../runner/KUBERNETES_RUNNER_README.md) for hosted
output and [RUNNER_README.md](../../runner/RUNNER_README.md) for local output). Bundles are constructed only when a
consumer asks for one.

## Bundle Contents

A bundle is a zip containing some subset of the following entries plus a `manifest.json` describing what's present:

| Token             | File(s) in zip                                                                 | Source artifact                                                                            |
| ----------------- | ------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------ |
| `results`         | `results.json`                                                                 | [Results](RESULTS.md) from `RESULTS_URI` / local file                                      |
| `replay`          | `replay` (uncompressed game-owned bytes)                                       | [Replay](REPLAY.md) from `REPLAY_URI` / local file                                         |
| `error_info`      | `error_info.json` (only present if the episode failed)                         | [Error info](ERROR_INFO.md) from `ERROR_INFO_URI`                                          |
| `game_logs`       | `logs/game.log`                                                                | [Game logs](GAME_LOGS.md) from hosted episode logs / local logs                            |
| `player_logs`     | `logs/policy_agent_{slot}.log` (subject to access control — see below)         | [Player logs](PLAYER_LOGS.md) from `POLICY_LOG_URLS` / local logs                          |
| `player_artifact` | `artifacts/policy_artifact_{slot}.zip` (subject to access control — see below) | [Player artifact](PLAYER_ARTIFACT.md) from `PLAYER_ARTIFACT_UPLOAD_URLS` / local workspace |

The bundle stores `replay` uncompressed since the outer zip already compresses. The runner's local workspace contains a
single `replay` file with the exact bytes the game container wrote; the hosted upload path zlib-compresses those bytes
in memory at the upload boundary for hosted upload and replay-viewing paths that consume the compressed form directly.

### `manifest.json`

Every bundle contains a `manifest.json` at the zip root describing its contents:

```json
{
  "ereq_id": "ereq_...",
  "status": "success",
  "include": ["results", "replay", "game_logs", "player_logs"],
  "files": {
    "results": "results.json",
    "replay": "replay",
    "game_logs": {
      "combined": "logs/game.log"
    },
    "player_logs": {
      "0": "logs/policy_agent_0.log",
      "1": "logs/policy_agent_1.log"
    }
  }
}
```

- `status` is `"success"` or `"failed"`. On `"failed"`, `error_info.json` is typically present and most other files may
  be absent.
- `include` echoes the tokens that the bundle was built with, after access-control filtering.
- `files` maps each included token to its entry name(s) inside the zip. Consumers should read from `files` rather than
  hard-coding paths; the layout above is the current convention but may evolve.

## Requesting a Bundle

The current package defines the consumer-side bundle contract used by Paint Arena reporters, including
`COGAME_EPISODE_BUNDLE_URI` and the `BundleReader` helper vendored under the Paint Arena reporter example.

The hosted bundle-request API is implemented by the Observatory backend. The CLI surface is still planned.

### Planned CLI

```bash
uv run coworld bundle ereq_... --output ep.zip
uv run coworld bundle ereq_... --output ep.zip --include results,replay,game_logs
```

When `--include` is omitted, the CLI should request every artifact the caller is permitted to see.

### API

```http
GET /v2/episode-requests/{ereq_id}/bundle?include=results,replay,player_logs
```

The response should be a `.zip` body with `Content-Type: application/zip`. Auth should follow the same model as the
episode-request artifact endpoints. The `include` query parameter should be comma-separated; omitting it should return
every artifact the requester is permitted to see.

Until the CLI surface lands, use the episode-request routes and per-artifact commands in
[COOKBOOK.md](../../../../COOKBOOK.md#retrieve-logs-results-and-replays) for interactive investigation:

```bash
uv run coworld episodes ereq_... --json                          # status, scores, replay_url
uv run coworld episode-logs ereq_... --game --download-dir logs/ # game log
uv run coworld replays --round round_... --mine --download-dir replays/
uv run coworld episode-results ereq_... --output results.json    # Softmax team accounts only
```

## Access Control

The bundling layer applies the same per-artifact authorization model the existing artifact endpoints use, with one
additional rule for player logs:

- **`results`, `replay`, `error_info`, `game_logs`**: anyone with episode access can include them.
- **`player_logs`**: by default, the bundle includes only the logs for player slots controlled by policy versions the
  requester owns. Softmax-internal requesters may receive all player logs.
- **`player_artifact`**: same policy-scoped rule as `player_logs` — by default only the artifacts for player slots the
  requester owns, with Softmax-internal requesters receiving all.

> **Game authors:** game container stdout and stderr are surfaced to _anyone_ with episode access via the `game_logs`
> token. Do not write secrets, private credentials, or other confidential information to those streams. See
> [GAME.md § Log Visibility](../roles/GAME.md#log-visibility).

If a requester asks for an `include` token they are not permitted to receive, the bundling layer silently omits that
token rather than failing the whole request. The returned `manifest.json`'s `include` field reflects what was actually
delivered.

## Consumption by Supporting Runnables

When an orchestrator invokes a supporting runnable — reporter, grader, diagnoser, or optimizer — it first assembles a
bundle and then hands it to the runnable via:

```bash
COGAME_EPISODE_BUNDLE_URI=file:///path/to/bundle.zip
COGAME_EPISODE_BUNDLE_URI=https://.../ep.zip
```

The runnable reads the zip, inspects its `manifest.json` to discover what's inside, and processes the files. The
runnable does not need to know whether the bundle came from a local workspace or a hosted artifact store.

Supporting-role outputs are separate artifacts, not entries in the episode bundle today:

- [Report](REPORT.md), optionally including an [event log](EVENT_LOG.md) or [trace](TRACE.md).
- [Grade](GRADE.md).
- [Diagnosis](DIAGNOSIS.md).
- [Optimizer outputs](OPTIMIZER_OUTPUTS.md).

See [REPORTER.md](../roles/REPORTER.md), [GRADER.md](../roles/GRADER.md), [DIAGNOSER.md](../roles/DIAGNOSER.md), and
[OPTIMIZER.md](../roles/OPTIMIZER.md) for each role's expected use of bundle contents.

## See Also

- [Artifact reference](README.md) for all Coworld artifacts.
- [Results](RESULTS.md), [replay](REPLAY.md), [debug archive](DEBUG_ARCHIVE.md), [game logs](GAME_LOGS.md),
  [player logs](PLAYER_LOGS.md), and [error info](ERROR_INFO.md) for source artifact contracts.
- [Coworld lifecycle](../LIFECYCLE.md) for local and hosted production timing.
