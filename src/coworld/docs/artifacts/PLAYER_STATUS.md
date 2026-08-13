# Player Status

`player_status.json` is the hosted runner's typed snapshot of player process state immediately before it deletes child
player pods. It preserves per-slot lifecycle evidence separately from game-authored scores and free-form logs.

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
- `not_started`: Kubernetes had not started the player container;
- `unavailable`: the runner could no longer read the pod status.

An `exited` state is deliberately neutral. Exit code `0` means only that the process returned zero; it does not prove
the player completed the game protocol. For example, a player may catch a WebSocket timeout and return zero before the
game ends. Compare `finished_at` with episode completion and inspect the player log. A game that needs authoritative
connection transitions should record those transitions in its own replay or event artifact.

Hosted jobs upload this artifact through `PLAYER_STATUS_URI`. Authorized episode consumers can fetch it from
`/v2/episode-requests/{episode_request_id}/artifacts/player-status`. Its absence on older episodes is expected.
