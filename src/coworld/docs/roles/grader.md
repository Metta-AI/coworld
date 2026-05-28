# Grader Role

**Status:** contract defined, runtime pending

> The manifest contract is active: every Coworld must declare at least one grader runnable. Grader execution remains
> on-demand; the episode runner does not automatically run graders when an episode finishes.

## What it does

The grader role emits a single scalar score reflecting how interesting or useful an episode was from the game creator's
perspective. Graders are the smallest of the supporting runnables — their entire output is one number (plus a tiny bit
of provenance) that downstream surfaces can use to rank, sort, surface, or hide episodes. Grader runs are on-demand:
they are triggered by a CLI command or platform action, not by the episode runner itself.

## Where it lives in the manifest

`manifest.grader[]`, with `type: "grader"` on every entry. The section is optional and may be empty until the platform
runs graders. See
[`MANIFEST_README.md`](../../MANIFEST_README.md) for the full runnable shape.

## Contract

A grader runnable is a short-lived, process-style container started by a CLI or platform action that wants a score for a
particular episode. It does not expose HTTP routes or websockets; it reads its input from an env-var URI, writes its
scalar output, and exits.

### Input

A grader receives one env var:

- `COGAME_EPISODE_BUNDLE_URI` — URI (file:// locally, https:// hosted) of a `.zip` file containing the episode's
  artifacts. Same bundle shape that reporters and other supporting runnables receive. See
  [`EPISODE_BUNDLE_README.md`](../../EPISODE_BUNDLE_README.md) for the full bundle contract.

A grader input bundle always contains `results.json` and `replay.json`; it may also contain `config.json`, game logs,
per-player logs (subject to access control), and `error_info.json` if the episode failed.

### Output

A grader writes its output to one env var:

- `COGAME_GRADE_URI` — URI (file:// locally, https:// or s3:// hosted) where the grader writes a single JSON file
  containing its score.

```json
{
  "grader_id": "among-them-grader",
  "score": 0.85
}
```

| Field       | Required?   | Purpose                                                                                                                                                                        |
| ----------- | ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `score`     | required    | The grade. Float; range and meaning are grader-defined (see open questions).                                                                                                   |
| `grader_id` | recommended | The id this grader self-reports for itself. Conventionally matches the runnable's `id` in `manifest.grader[]`. Useful for caches and downstream consumers tracking provenance. |

Additional grader-specific fields may be included in the JSON; consumers should ignore fields they do not recognize.

### Execution

Graders are on-demand. They are **not** run automatically by the episode runner; an episode finishes and produces
artifacts whether or not any grader ever runs against them.

A grader run is triggered by a CLI command, a hosted button, or an automatic Column pipeline that ranks episodes for
downstream attention. The invoker is responsible for:

1. Choosing which grader to run (one of the runnables in `manifest.grader[]`).
2. Assembling the input bundle via the bundling layer.
3. Setting `COGAME_EPISODE_BUNDLE_URI` and `COGAME_GRADE_URI` on the grader container.
4. Waiting for the container to exit and consuming the output JSON.

### Determinism

Graders are **not required** to produce identical scores across runs over identical inputs, but should do so when
feasible. Deterministic graders enable caching, reproducible ranking, and stable test fixtures. LLM-based or otherwise
non-deterministic graders are also valid.

## Open questions

The grader role has normalization questions that are still unresolved. They are listed here so future work knows where
the load-bearing decisions still live.

- **Score range and normalization.** Currently the contract leaves `score` as an unconstrained float and tells graders
  to document their own scale in `description`. The open question is whether to instead require a canonical range (e.g.
  0–1, -1 to 1) so scores can be compared across graders. Both directions have real costs: unconstrained scores aren't
  comparable across graders; canonical scores push interpretation burden onto the grader. This is the most load-bearing
  open question; the answer will likely come from the first concrete ranking use case.
- **Comparability across graders.** Tied to the range question. Today's contract says grader scores are not directly
  comparable. A normalization decision may change this.
- **Multi-grader aggregation.** When multiple graders score the same episode, is there a meaningful way to combine their
  scores into a single ranking signal? Not addressed in v1.

## How it fits with other roles

Graders live in the post-episode artifact layer alongside reporters, diagnosers, and optimizers. They consume the same
episode-bundle input shape as the other supporting runnables, but their output is intentionally tiny: a single scalar
that can be used by humans or automated pipelines to decide which episodes are worth a closer look.

Graders are deliberately smaller than reporters: reporters produce human-readable summaries and structured event logs;
graders produce a single ranking signal. The two roles complement each other — a grader picks the episodes worth
attention; a reporter explains what happened in those episodes. See [`OVERVIEW.md`](OVERVIEW.md) for the full artifact
flow.

## See Also

- [`EPISODE_BUNDLE_README.md`](../../EPISODE_BUNDLE_README.md) — full bundle contract the grader consumes.
- [`MANIFEST_README.md`](../../MANIFEST_README.md) — manifest field reference for `manifest.grader[]`.
- [`COWORLD_README.md`](../../COWORLD_README.md) — Role Status framework, runnable conventions.
- [`reporter.md`](reporter.md) — sibling supporting runnable; richer output, complementary purpose.
- [`diagnoser.md`](diagnoser.md), [`optimizer.md`](optimizer.md) — other sibling supporting runnables.
- [`OVERVIEW.md`](OVERVIEW.md) — full artifact flow.
