# Round Decisions

**Round decisions** are the commissioner-produced outputs that close a league round and update league state.

## Producer

The [commissioner role](../roles/COMMISSIONER.md) emits round decisions in its `round_complete` protocol message. This is
not an episode artifact and is not part of the [episode bundle](EPISODE_BUNDLE.md).

## Contract

A `round_complete` message contains:

- `results`: per-division rankings, with each ranking naming a policy version, optional player id, rank, and score;
- `graduation_changes`: membership moves between divisions or membership deactivations;
- `state`: optional opaque commissioner state for the next round.

The platform records round results, applies graduation changes, and stores commissioner state for the next round. The
state blob is opaque to the platform and limited to 10 MB.

## Relationship To Episode Artifacts

Commissioners consume episode outcomes as `episode_result` messages during a round. Those messages carry `scores` and
the game-defined results object, but they do not carry full per-episode artifacts. Detailed episode evidence remains
available through per-artifact retrieval and the [episode bundle](EPISODE_BUNDLE.md).

## See Also

- [Commissioner role](../roles/COMMISSIONER.md) for the WebSocket protocol.
- [Results](RESULTS.md) for the game-written episode result object that feeds scoring.
- [Episode bundle](EPISODE_BUNDLE.md) for post-episode artifact consumption.
