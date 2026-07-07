# Results Artifact

The **results artifact** is the game-written JSON object that records the final outcome of one episode.

## Producer

The [game role](../roles/GAME.md) writes results at the end of rollout mode:

- local runner: `results.json` in the artifact workspace;
- hosted runner: bytes uploaded to `RESULTS_URI`;
- game container input: `COGAME_RESULTS_URI`.

The local and hosted runners validate the JSON against `manifest.game.results_schema` after the game exits. A Coworld
game must include `scores`, one numeric score per player slot, because commissioners and leaderboard aggregation use
those values to rank policy versions. Games may include additional game-specific fields when those fields are declared by
the results schema.

## Consumers

Results are consumed by:

- the platform, which turns `scores` into per-policy episode and round results;
- commissioners, which receive completed episode results during round scheduling;
- graders, diagnosers, and optimizers through the [episode bundle](EPISODE_BUNDLE.md) `results` token; reporters
  through their `episodes` tool (spec 0061);
- humans and agents through the per-policy `scores` on episode request rows (`coworld episodes ereq_... --json`);
  the raw `results.json` is served only by `coworld episode-results` / `GET /jobs/{job_id}/artifacts/results`, which
  are restricted to Softmax team accounts.

## Contract

- Format: JSON object.
- Validation: must satisfy `manifest.game.results_schema`.
- Required cross-game field: `scores`, one number per player slot.
- Local filename: `results.json`.
- Hosted artifact: `RESULTS_URI`, uploaded as `application/json`.
- Episode bundle entry: `results.json`.

Results are the source of truth for episode scoring. Logs and reports can explain what happened, but they do not replace
the results artifact.

## See Also

- [Game role](../roles/GAME.md) for the producer contract.
- [Episode bundle](EPISODE_BUNDLE.md) for bundled consumption.
- [Lifecycle](../LIFECYCLE.md) for local and hosted validation timing.
