# Debug Archive

The **debug archive** is the hosted runner's zip of diagnostic log files for one episode.

## Producer

The hosted Kubernetes runner writes a zip to `DEBUG_URI` after it has collected whatever logs are available in its
episode workdir. The local runner does not upload a debug archive; its equivalent content stays in the local `logs/`
directory.

## Contents

The archive is a zip of the runner's log directory. It may include:

- `game.stdout.log`;
- `game.stderr.log`;
- `policy_agent_{slot}.log` for any player pod logs the coordinator captured.

Player logs are also uploaded individually through `POLICY_LOG_URLS` when configured. The debug archive is the aggregate
diagnostic package; per-player log artifacts are the access-controlled policy-owner view.

## Contract

- Hosted artifact: `DEBUG_URI`.
- Content type: `application/zip`.
- Archive layout: files from the runner's log directory are written at the zip root.
- Purpose: diagnostics and post-failure investigation only.

## Visibility

Treat the debug archive as a runner diagnostic source, not a user-facing authorization unit. Public surfaces split it
into game-log and player-log views: game stdout/stderr are public to anyone with episode access, while player logs remain
policy-scoped by default when served through player-log routes or episode bundles. Do not write secrets or private
credentials to any container stdout, stderr, or optional log-posting endpoint.

## Relationship To Bundles

The episode bundle does not include `debug.zip` as a single file. Instead, the bundling layer extracts the relevant
entries into the [game logs](GAME_LOGS.md) and [player logs](PLAYER_LOGS.md) include tokens.

## See Also

- [Game logs](GAME_LOGS.md) for game-container stdout and stderr.
- [Player logs](PLAYER_LOGS.md) for per-slot player diagnostics.
- [Episode bundle](EPISODE_BUNDLE.md) for bundled log entries.
- [Lifecycle](../LIFECYCLE.md) for hosted upload timing.
