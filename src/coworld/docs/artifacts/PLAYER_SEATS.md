# Player Seats

`player_seats.json` is the game-hosted player input and output contract. The runner stages every submitted player file,
writes this document, and passes its URI to the game as `COGAME_PLAYER_SEATS_URI`. Local and hosted runners currently
use `file:///coworld/player_seats.json`.

```json
{
  "schema": "coworld-player-seats/1",
  "seats": [
    {
      "slot": 0,
      "file_uri": "file:///coworld/players/0/file",
      "content_hash": "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
      "size_bytes": 12345,
      "log_uri": "file:///coworld/logs/policy_agent_0.log",
      "artifact_uri": "file:///coworld/policy_artifact_0.zip"
    }
  ],
  "player_status_uri": "file:///coworld/player_status.json"
}
```

## Fields

- `schema` is exactly `coworld-player-seats/1`.
- `seats` is a non-empty ordered list. `slot` is the zero-based episode seat used by results, logs, artifacts, and
  ownership checks.
- `file_uri` identifies the staged player bytes. The current layout is `/coworld/players/{slot}/file`.
- `content_hash` is the lowercase SHA-256 digest of those bytes, prefixed with `sha256:`.
- `size_bytes` is the byte length verified before the game starts.
- `log_uri` is where the game writes that seat's private diagnostic log. The game must create one log per slot, even
  when it is empty.
- `artifact_uri` is where the game may write one optional per-seat artifact. Hosted upload accepts a non-empty file up
  to 200 MiB and stores it as `application/zip` without inspecting its contents.
- `player_status_uri` is where the game may write the optional [`player_status.json`](PLAYER_STATUS.md) diagnostic
  snapshot.

The game must finish writing every `log_uri`, `artifact_uri`, and `player_status_uri` output before it writes
`results.json`. That file is the game-hosted completion marker. The worker begins collection when results and the
required replay exist, without waiting for the game server to exit.

The document contains no policy name, player identity, owner identity, signed download URL, or upload capability. The
trusted init container downloads and verifies the player bytes before writing local `file://` references.

## Ownership And Privacy

The game process can read every staged player file. Submitting a file policy to a game-hosted Coworld therefore shares
those bytes with code controlled by the Coworld author. Use a platform-hosted Coworld when that trust boundary is not
acceptable.

Player logs and artifacts remain policy-scoped after upload, but the game must keep seat output separate. Never copy
player output into game stdout or stderr because game logs may be visible to anyone who can access the episode.

## See Also

- [Game role](../roles/GAME.md) for execution and output responsibilities.
- [Player role](../roles/PLAYER.md) for file-policy upload and visibility.
- [Player logs](PLAYER_LOGS.md), [player status](PLAYER_STATUS.md), and [player artifacts](PLAYER_ARTIFACT.md) for the
  output contracts.
