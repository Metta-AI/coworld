# Game Logs

**Game logs** are diagnostic output from the game container for one episode.

## Producer

Game logs come from the game container and the runner:

- local runner: `logs/game.stdout.log` and `logs/game.stderr.log`;
- hosted runner: game pod logs collected into the [debug archive](DEBUG_ARCHIVE.md) at `DEBUG_URI`;
- optional game-side log posting: `COGAME_LOG_URI`, when supplied.

`COGAME_LOG_URI` is optional. If it is unset, the game must skip log posting and may still write stdout/stderr normally.

## Visibility

Game stdout and stderr are visible to anyone with episode access through hosted log routes and the
[episode bundle](EPISODE_BUNDLE.md) `game_logs` token. Treat them as public. Do not write secrets, private credentials,
tokens, or private player data to game stdout, stderr, `COGAME_LOG_URI`, global WebSocket messages, or browser-served
client pages.

## Contract

- Local filenames: `logs/game.stdout.log`, `logs/game.stderr.log`.
- Hosted artifact: exposed by Observatory as combined episode logs.
- Episode bundle entry: `logs/game.log`.
- Purpose: diagnostics and debugging only.

Game logs are not the source of truth for episode success. Results and replay upload remain the success-critical
artifacts.

## See Also

- [Game role](../roles/GAME.md) for logging and visibility guidance.
- [Debug archive](DEBUG_ARCHIVE.md) for hosted aggregate log storage.
- [Episode bundle](EPISODE_BUNDLE.md) for bundled consumption.
- [Player logs](PLAYER_LOGS.md) for policy-container logs.
