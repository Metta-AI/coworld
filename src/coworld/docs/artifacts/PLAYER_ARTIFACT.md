# Player Artifact

A **player artifact** is an optional per-seat file for debug data, separate from [player logs](PLAYER_LOGS.md). It is
intended for profiling and post-hoc analysis.

## Producer

The producer depends on `game.player_runtime`:

- platform-hosted: the player container uploads through `COWORLD_PLAYER_ARTIFACT_UPLOAD_URL`;
- game-hosted: the game writes to the seat's `artifact_uri` from [`player_seats.json`](PLAYER_SEATS.md), then the worker
  uploads it;
- local platform-hosted: a `file://` URL points into a private Docker-owned volume mounted at `/coworld-artifact`. After
  containers stop, the latest regular file is collected as `policy_artifact_{slot}.zip`, including on episode failure.
  Sibling artifacts, logs, and game outputs are not mounted into players. Symlinks and special files are not collected;
- hosted output: `PLAYER_ARTIFACT_UPLOAD_URLS` maps slots to final upload targets.

If `COWORLD_PLAYER_ARTIFACT_UPLOAD_URL` is absent, a platform-hosted player skips uploading. The platform never reaches
into that container's filesystem. In game-hosted mode, absence of the `artifact_uri` file means no artifact.

## Upload window

A platform-hosted player may replace the object during the episode and must finish before pod teardown. A game-hosted
game must finish writing every seat artifact before writing `results.json`. The worker treats results as the completion
marker and begins collection when results and the required replay exist; it does not wait for the game server to exit.

## Contract

- The default path keeps one live object per player slot. Each successful upload replaces that live object's contents.
  Long-running sessions can additionally retain explicit captures using the protocol below.
- Maximum size: 200 MiB (209,715,200 bytes). The worker skips an oversized game-hosted file without failing the episode.
- A game-hosted worker records the file size, sends that value as `Content-Length`, and makes one upload attempt. A file
  that grows during upload is skipped without failing the episode.
- Format: a `.zip`. The player may bundle whatever it wants inside (parquet, sqlite, csv, json, trace files). The
  platform stores and serves the bytes as-is and does not unzip them. The `.zip` extension is a storage convention, not
  an enforced format.
- Local filename: `policy_artifact_{slot}.zip` in the workspace root.
- Hosted key: `jobs/{job_id}/policy_artifact_{slot}.zip`.
- Content type: `application/zip`.
- Purpose: profiling and debugging only.

The two profiling approaches this enables:

- **Sampling profiler** (records everything): dump all per-step state into a file, zip, upload. Useful initially but
  becomes noise.
- **Tracing profiler** (records specific events): record only named events. Better for optimization once you know what
  to look for.

Missing, empty, and failed artifact uploads do not fail an otherwise successful episode. Results and replay remain
success-critical.

## Retained captures from long-running sessions

A Persistent runtime can retain multiple uploads through its existing `COWORLD_PLAYER_ARTIFACT_UPLOAD_URL`. Send a
normal ZIP `PUT` with the additional `X-Coworld-Artifact-Capture` header:

```json
{ "capture_id": "<UUID>", "started_at": "2026-09-01T00:00:00Z", "ended_at": "2026-09-01T00:05:00Z" }
```

The producer chooses the capture UUID and reports what time span its diagnostics cover. Times must include a timezone;
`ended_at` must follow `started_at`. Upload time does not establish capture coverage. A successful upload returns HTTP
201 and a JSON reference:

```json
{ "runtime_id": "<UUID>", "session_id": "<UUID>", "artifact_id": "<SHA-256>" }
```

The producer passes this reference to its game's scoring-window recorder. The game's `coworld.recorded_window.v1` feed
includes the selected references in `player_artifacts` (at most 16 per episode). Scoring persists those references
without reading artifact storage. The producer owns choosing relevant captures and handling upload failures; a missing
capture does not prevent score ingestion. Existing producers must implement this exchange to retain historical evidence.

The trusted worker adds launch provenance, hashes the bytes, and writes the ZIP and a manifest under
`jobs/{runtime_id}/sessions/{session_id}/artifacts/{artifact_id}/`. The artifact ID hashes the canonical manifest,
including capture metadata, session provenance, size, and content digest. Identical retries reuse the same reference;
changed bytes or metadata produce another reference. The worker holds one expiring, session-prefix-scoped storage POST
capability. Players receive neither that capability nor arbitrary storage keys.

Immutability is content-addressed, not an S3 write-once lock. Episode downloads verify manifest identity and content
hashes before returning bytes. An overwritten or missing object is reported as corrupt or missing; it never resolves to
the latest live checkpoint. No game-specific archive parsing occurs in Observatory.

Limits: 200 MiB per ZIP, 128 distinct captures and 512 MiB of retained ZIP bytes per session. Reservations are written
before upload to the worker's job volume. Failed uploads consume their reservation; identical retries reuse it. The
worker returns HTTP 429 when the session budget is exhausted. Capability refresh does not reset the budget. A new
controller launch has a new session and budget. There is no automatic periodic capture or age-based deletion in this
protocol; the private bucket's retention policy still applies. Downloads also enforce a 512 MiB aggregate limit.

Omitting the capture header retains the ordinary replaceable-live-checkpoint behavior. Retained captures do not replace
that checkpoint. Runtimes without retained-upload capabilities reject capture requests; producers should treat retained
capture upload as optional diagnostics, separately from gameplay and scoring.

## Visibility

The access model is policy-scoped, matching player logs: a requester receives only artifacts for slots controlled by
policy versions they own. Team members may access every slot for debugging.

Ownership-scoped route:

- `GET /v2/episode-requests/{episode_request_id}/{policy_version_id}/policy-artifact/{agent_idx}` returns the `.zip` for
  one owned policy version and one agent slot. The route verifies that the policy version participated in that episode
  and that the requested agent slot actually ran that policy.

Team-only maintenance routes:

- `GET /jobs/{job_id}/policy-artifact` lists the slots that uploaded an artifact.
- `GET /jobs/{job_id}/policy-artifact/{agent_idx}` returns the `.zip` for a slot.

The CLI uses those routes for inspection:

```bash
uv run coworld episode-logs ereq_... --agent 0 --artifact --download-dir logs/
uv run coworld replay-open ereq_... --with-artifacts --artifacts-dir artifacts/
```

## See Also

- [Player logs](PLAYER_LOGS.md) for stdout/stderr diagnostics.
- [Player role](../roles/PLAYER.md) for the producer contract.
- [Episode bundle](EPISODE_BUNDLE.md) for access-controlled bundled consumption.
