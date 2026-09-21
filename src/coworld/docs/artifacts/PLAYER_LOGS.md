# Player Logs

**Player logs** are private per-seat diagnostic output for one episode.

## Producer

The producer depends on `game.player_runtime`:

- platform-hosted: the runner captures each player container's combined stdout and stderr;
- game-hosted: the game writes each file named by the `log_uri` in [`player_seats.json`](PLAYER_SEATS.md);
- local runner: both modes use `logs/policy_agent_{slot}.log`;
- hosted runner: both modes upload one object per slot through `POLICY_LOG_URLS`;
- hosted debug archive: also included in the [debug archive](DEBUG_ARCHIVE.md) when collected.

For platform-hosted jobs, the runner reads up to the last 10,000 pod-log lines from started player containers. That is
a tail: a player that writes more than 10,000 lines in an episode keeps only the last 10,000, so the captured log loses
the beginning of the episode, not the end. A policy that needs its complete log should upload it as a
[player artifact](PLAYER_ARTIFACT.md), which has no line cap. For game-hosted jobs, the game decides what one seat log
contains.

## Visibility

Player logs are policy-scoped by default. A requester receives only logs for slots controlled by policy versions they
own, unless the requester has internal access. The [episode bundle](EPISODE_BUNDLE.md) applies the same filtering to the
`player_logs` token.

Serving routes:

- `GET /v2/episode-requests/{episode_request_id}/{policy_version_id}/policy-logs/{agent_idx}` — the policy-scoped route
  described above (you must own the policy version that ran the slot; Softmax team accounts can read all slots).
- `GET /jobs/{job_id}/policy-logs` and `GET /jobs/{job_id}/policy-logs/{agent_idx}` — list/fetch by job ID; restricted
  to Softmax team accounts.

## Contract

- Local filename: `logs/policy_agent_{slot}.log`.
- Hosted artifact: `POLICY_LOG_URLS`, a JSON object mapping slot indexes to per-log upload URIs.
- Episode bundle entries: `logs/policy_agent_{slot}.log`.
- Content: `text/plain`; combined container output or game-authored per-seat diagnostics.
- Maximum uploaded size: 10 MiB per slot. The hosted runner appends `[truncated by the runner at 10 MiB]` when it
  truncates a longer log.
- Purpose: diagnostics and debugging only.

Missing player logs do not fail an otherwise successful episode. The hosted game-hosted worker creates a diagnostic
placeholder for every missing slot before upload. Results and replay remain the success-critical artifacts.

Game-hosted authors must never route player output through game stdout or stderr. Game logs may be visible to anyone
with episode access, while player logs use the policy ownership gate. The platform cannot enforce this separation inside
the game process.

## See Also

- [Player role](../roles/PLAYER.md) for the producer contract.
- [Debug archive](DEBUG_ARCHIVE.md) for hosted aggregate log storage.
- [Episode bundle](EPISODE_BUNDLE.md) for access-controlled bundled consumption.
- [Game logs](GAME_LOGS.md) for game-container logs.
