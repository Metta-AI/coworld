# Replay Artifact

The **replay artifact** is the game-written byte stream that lets the same game image replay one completed episode.

## Producer

The [game role](../roles/GAME.md) writes replay bytes during rollout mode:

- local runner: `replay` in the artifact workspace;
- hosted runner: bytes uploaded to `REPLAY_URI`;
- game container input: `COGAME_SAVE_REPLAY_URI`.

The local workspace stores the exact bytes the game wrote. The hosted runner zlib-compresses those bytes in memory at
the upload boundary and stores the hosted object as `replay.json.z`.

## Format

Replay format is game-owned. The Coworld platform treats the replay as bytes and routes it back to the same game image
in replay mode. A game must be able to serve replay viewing when started with:

```bash
COGAME_LOAD_REPLAY_URI=file:///coworld/replay
```

The replay viewer enters through `/client/replay`, and the replay WebSocket uses `/replay`. The runner supplies the
replay artifact location through `COGAME_LOAD_REPLAY_URI` when it starts the replay container. Hosted Observatory replay
sessions pass the hosted `replay.json.z` artifact URI directly through `COGAME_LOAD_REPLAY_URI`.

`GET /client/replay` starts playback automatically by default. When playback reaches the recorded end, the viewer loops
back to tick 0 and continues until a user pauses or seeks.

## Consumers

Replays are consumed by:

- replay viewers, either local or hosted;
- reporters, graders, diagnosers, and optimizers through the [episode bundle](EPISODE_BUNDLE.md) `replay` token;
- humans and agents through `coworld replay` for local replay files and `coworld replays` / `coworld replay-open` for
  hosted episode artifacts.

The episode bundle stores replay bytes as `replay.json` inside the outer zip. Hosted storage may use compressed
`replay.json.z`, but bundle consumers should treat the bundled `replay` token as the uncompressed replay payload.

## Contract

- Format: game-owned byte payload.
- Local filename: `replay`.
- Hosted artifact: `REPLAY_URI`, stored as zlib-compressed `replay.json.z`.
- Episode bundle entry: `replay.json`.
- Replay server mode: same game image, with `COGAME_LOAD_REPLAY_URI` pointing at the replay bytes.
- Replay viewer default: autoplay and loop from the recorded end back to tick 0.

Certification checks that the replay file exists and that the game image can start a replay viewer for it.

## See Also

- [Game role](../roles/GAME.md) for replay-mode routes.
- [Episode bundle](EPISODE_BUNDLE.md) for bundled consumption.
- [Lifecycle](../LIFECYCLE.md) for local and hosted replay differences.
