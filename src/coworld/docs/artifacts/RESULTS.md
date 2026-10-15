# Results Artifact

The **results artifact** is the game-written JSON object that records the final outcome of one episode.

## Producer

The [game role](../roles/GAME.md) writes results at the end of rollout mode:

- local runner: `results.json` in the artifact workspace;
- hosted runner: bytes uploaded to `RESULTS_URI`;
- game container input: `COGAME_RESULTS_URI`.

The local and hosted runners validate the JSON against `manifest.game.results_schema` after the game exits. A Coworld
game must include `scores`, one numeric score per player slot, because commissioners and leaderboard aggregation use
those values to rank policy versions. Games may include additional game-specific fields when those fields are declared
by the results schema.

## Consumers

Results are consumed by:

- the platform, which turns `scores` into per-policy episode and round results;
- commissioners, which receive completed episode results during round scheduling;
- graders, diagnosers, and optimizers through the [episode bundle](EPISODE_BUNDLE.md) `results` token; reporters through
  their `episodes` tool (spec 0061);
- humans and agents through the per-policy `scores` on episode request rows (`coworld episodes ereq_... --json`); the
  raw `results.json` is served only by `coworld episode-results` / `GET /jobs/{job_id}/artifacts/results`, which are
  restricted to Softmax team accounts.

## Contract

- Format: JSON object.
- Validation: must satisfy `manifest.game.results_schema`.
- Required cross-game field: `scores`, one number per player slot.
- Optional cross-game field: `roles`, one seat-role entry per player slot, in the same order as `scores`.
- Local filename: `results.json`.
- Hosted artifact: `RESULTS_URI`, uploaded as `application/json`.
- Episode bundle entry: `results.json`.

Results are the source of truth for episode scoring. Logs and reports can explain what happened, but they do not replace
the results artifact.

### Seat roles

Games with asymmetric seats may export `roles`: one entry per player slot, in the same order as `scores`. Each entry is
a non-empty string such as `"France"` or `"healer"`, or a non-empty list of non-empty strings for a seat that holds
several role attributes at once, such as `["cooperator", "adversary", "listener", "pursuer"]`. Labels are case-sensitive
and kept exactly as exported. Duplicate labels are allowed: several seats may share a role. Omitting `roles` or setting
it to `null` means no roles were reported. Declare the field in `game.results_schema` when exporting it; no manifest
role catalog is required.

Labels have meaning only within a variant. The same label in two variants identifies different roles. Report each slot's
actual role for that episode, including when roles are randomly assigned. Keep `scores` unadjusted.

The platform adds no cross-game check of `roles` at hosted finalization: only the game's own `results_schema` applies,
as for any other field it declares. The raw value is stored with the results, and a consumer that uses roles checks
their shape, so a game whose `roles` field means something else keeps working everywhere else.

**OpenSkill integration:** leagues with `ranking.role_advantage_sigma` set learn role advantages separately from player
ratings, keyed by variant and role within each league. A list entry is one composite role, distinct from every single
label. These leagues check `roles` when they load an episode: it must be a list with one entry per seat in the shape
above, or settlement of that round fails loudly. Forfeits, solo benchmarks, and episodes without roles or a variant rate
players only. Roles come from non-filler seats of retained subjects; dropped sides contribute no roles. Published
ratings remain player-only. See [platform ladder settings](../PLATFORM_LADDER_LEAGUE.md#role-advantages).

## See Also

- [Game role](../roles/GAME.md) for the producer contract.
- [Episode bundle](EPISODE_BUNDLE.md) for bundled consumption.
- [Lifecycle](../LIFECYCLE.md) for local and hosted validation timing.
