# Player Artifact

A **player artifact** is an optional file a player uploads at the end of an episode to save debug data —
separate from [player logs](PLAYER_LOGS.md). It is intended for profiling and post-hoc analysis where stdout/stderr
logs are too large or too unstructured (logs routinely grow to gigabytes).

## Producer

The player container uploads the artifact itself. The runner hands each player a single presigned upload URL via the
`COWORLD_PLAYER_ARTIFACT_UPLOAD_URL` environment variable:

- local runner: a `file://` URL into the workspace (the workspace is mounted into the player container at
  `/coworld-artifact`), collected as `policy_artifact_{slot}.zip`;
- hosted runner: a presigned `PUT` URL derived from `PLAYER_ARTIFACT_UPLOAD_URLS` (a JSON object mapping slot -> URL),
  forwarded into the player pod by the worker.

If the variable is absent, the player skips uploading. The platform never reaches into the player container's
filesystem; the player must perform the upload.

## Upload window

The player may upload at any time. Once the game finishes, the player container/pod stays alive only for a bounded
teardown timeout — the player must complete the upload before teardown or the artifact is lost. The platform does not
block teardown waiting for an upload.

## Contract

- Exactly one object per player slot.
- Maximum size: 200 MB.
- Format: a `.zip`. The player may bundle whatever it wants inside (parquet, sqlite, csv, json, trace files). The
  platform stores and serves the bytes as-is and does not unzip them. The `.zip` extension is a storage convention,
  not an enforced format.
- Local filename: `policy_artifact_{slot}.zip` in the workspace root.
- Hosted key: `jobs/{job_id}/policy_artifact_{slot}.zip`.
- Content type: `application/zip`.
- Purpose: profiling and debugging only.

The two profiling approaches this enables:

- **Sampling profiler** (records everything): dump all per-step state into a file, zip, upload. Useful initially but
  becomes noise.
- **Tracing profiler** (records specific events): record only named events. Better for optimization once you know
  what to look for.

Missing artifacts do not fail an otherwise successful episode. Results and replay upload remain the
success-critical artifacts.

## Visibility

The access model is policy-scoped, matching player logs: a requester receives only artifacts for slots controlled by
policy versions they own. Team members may access every slot for debugging.

Ownership-scoped route:

- `GET /v2/episode-requests/{episode_request_id}/{policy_version_id}/policy-artifact/{agent_idx}` returns the `.zip`
  for one owned policy version and one agent slot. The route verifies that the policy version participated in that
  episode and that the requested agent slot actually ran that policy.

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
