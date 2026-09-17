# Player Status

`player_status.json` is optional per-slot process evidence, separate from game-authored scores and free-form logs. The
hosted runner writes it for platform-hosted child pods. A game-hosted game may write it to the `player_status_uri` in
[`player_seats.json`](PLAYER_SEATS.md).

The artifact has this shape:

```json
{
  "schema_version": "1",
  "players": [
    {
      "slot": 0,
      "state": "exited",
      "exit_code": 0,
      "reason": "Completed",
      "finished_at": "2026-08-12T18:42:00Z"
    }
  ]
}
```

`state` is one of:

- `running`: the player process was still running when the game artifacts completed or the episode failed;
- `exited`: the process had exited; inspect `exit_code`, `reason`, `finished_at`, and that slot's player log;
- `not_started`: the player process did not start;
- `unavailable`: process status could not be determined.

An `exited` state is deliberately neutral. Exit code `0` means only that the process returned zero; it does not prove
the player completed the game protocol. For example, a player may catch a WebSocket timeout and return zero before the
game ends. Compare `finished_at` with episode completion and inspect the player log. A game that needs authoritative
connection transitions should record those transitions in its own replay or event artifact.

For game-hosted episodes, this file is a diagnostic statement from the game. The platform never uses it to decide the
episode result or blame a policy. The worker reads at most 1 MiB plus one byte and validates the exact schema above. It
logs and discards an oversized or invalid file, then continues the episode. Absence is normal.

Hosted jobs upload a valid artifact through `PLAYER_STATUS_URI`. Authorized episode consumers can fetch it from
`/v2/episode-requests/{episode_request_id}/artifacts/player-status`. Its absence on older episodes is expected.
