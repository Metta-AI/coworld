# Player Logs

**Player logs** are diagnostic output from each player container for one episode.

## Producer

Player logs come from player container stdout and stderr, captured by the runner:

- local runner: `logs/policy_agent_{slot}.log`;
- hosted runner: one object per slot through `POLICY_LOG_URLS`;
- hosted debug archive: also included in the [debug archive](DEBUG_ARCHIVE.md) when collected.

The local runner captures combined stdout and stderr for each player process. The hosted runner reads up to the last
10,000 pod-log lines from player containers that have started.

## Visibility

Player logs are policy-scoped by default. A requester receives only logs for slots controlled by policy versions they
own, unless the requester has internal access. The [episode bundle](EPISODE_BUNDLE.md) applies the same filtering to the
`player_logs` token.

## Contract

- Local filename: `logs/policy_agent_{slot}.log`.
- Hosted artifact: `POLICY_LOG_URLS`, a JSON object mapping slot indexes to per-log upload URIs.
- Episode bundle entries: `logs/policy_agent_{slot}.log`.
- Content: text/plain, combined stdout and stderr.
- Purpose: diagnostics and debugging only.

Missing player logs do not fail an otherwise successful episode. Results and replay upload remain the success-critical
artifacts.

## See Also

- [Player role](../roles/PLAYER.md) for the producer contract.
- [Debug archive](DEBUG_ARCHIVE.md) for hosted aggregate log storage.
- [Episode bundle](EPISODE_BUNDLE.md) for access-controlled bundled consumption.
- [Game logs](GAME_LOGS.md) for game-container logs.
