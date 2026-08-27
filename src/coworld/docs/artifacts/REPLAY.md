# Replay Artifact

The **replay artifact** is the game-written byte stream from one completed episode. A game-owned static browser bundle
or the version-matched game image turns those bytes into a viewable replay.

## Producer

The [game role](../roles/GAME.md) writes replay bytes during rollout mode:

- local runner: `replay` in the artifact workspace;
- hosted runner: bytes uploaded to `REPLAY_URI`;
- game container input: `COGAME_SAVE_REPLAY_URI`.

Both local and hosted runners store the exact bytes the game wrote. Hosted runner output uses `replay.replay` in the
eval artifact store and public replay URLs ending in `.replay`. The public browser copy is byte-identical unless the
manifest declares `game.replay_viewer.replay_compression: "gzip"`, which stores that copy (and only that copy) as gzip
bytes — see [Static Replay Viewers](../STATIC_REPLAY_VIEWERS.md).

## Format

Replay format is game-owned. The Coworld platform treats the replay as bytes. If the manifest declares
`game.replay_viewer.bundle`, Observatory loads its inferred `index.html` and supplies the hosted replay URL through the
`replay` fragment parameter (`#replay=`), with a shared `?v=` cache-buster on the entry HTML. A host bootstrap copies
that value into the `replay` query so already-uploaded bundles that only read `location.search` keep working. Removing
the bootstrap later requires bumping `v`. The bundle may parse recorded presentation state directly or execute a WASM
resimulator.

Without a static bundle, the platform routes the replay back to the same game image. That image must serve replay
viewing when started with:

```bash
COGAME_LOAD_REPLAY_URI=file:///coworld/replay
```

The replay viewer enters through `/client/replay`, and the replay WebSocket uses `/replay`. The runner supplies the
replay artifact location through `COGAME_LOAD_REPLAY_URI` when it starts the replay container. Hosted Observatory replay
sessions pass the hosted `.replay` artifact URI directly through `COGAME_LOAD_REPLAY_URI`.

`GET /client/replay` starts playback automatically by default. When playback reaches the recorded end, the viewer loops
back to tick 0 and continues until a user pauses or seeks.

## Consumers

Replays are consumed by:

- replay viewers, either local or hosted;
- graders, diagnosers, and optimizers through the [episode bundle](EPISODE_BUNDLE.md) `replay` token; reporters
  through their `episodes` tool (spec 0061);
- humans and agents through `coworld replay` for local replay files and `coworld replays` / `coworld replay-open` for
  hosted episode artifacts.

Hosted replays are discovered through the `replay_url` field on episode request rows (round episodes and Experience
Request children alike), set once the episode job completes. `coworld replay-open ereq_...` serves that artifact through
a local Docker game container; `coworld replay-open ereq_... --hosted` posts `{coworld_id, replay_uri}` to
`POST /v2/coworlds/replays/session` and opens the returned hosted viewer URL. See
[Cookbook: Retrieve Logs, Results, And Replays](../../../../COOKBOOK.md#retrieve-logs-results-and-replays).

The episode bundle stores replay bytes as `replay` inside the outer zip. Bundle consumers should treat the bundled
`replay` token as the raw replay payload.

## Contract

- Format: game-owned byte payload.
- Local filename: `replay`.
- Hosted artifact: `REPLAY_URI`, stored as raw `replay.replay`.
- Episode bundle entry: `replay`.
- Static viewer mode: immutable bundle `index.html`, with a host-bootstrapped `#replay=` fragment that does not vary
  the entrypoint's network URL (`?replay=` remains a local/legacy fallback).
- Fallback replay server mode: same game image, with `COGAME_LOAD_REPLAY_URI` pointing at the replay bytes.
- Replay viewer default: autoplay and loop from the recorded end back to tick 0.

Certification checks that the replay file exists. Without a declared static bundle, it also verifies that the game
image can load the replay through `/client/replay` and `/replay`. A declared static bundle replaces that legacy route
requirement and must be verified in a browser before upload.

## See Also

- [Game role](../roles/GAME.md) for replay-mode routes.
- [Static replay viewers](../STATIC_REPLAY_VIEWERS.md) for bundle generation, Coworld build hooks, and source-sharing
  guidance.
- [Episode bundle](EPISODE_BUNDLE.md) for bundled consumption.
- [Lifecycle](../LIFECYCLE.md) for local and hosted replay differences.
