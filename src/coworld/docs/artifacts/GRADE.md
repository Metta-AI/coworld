# Grade Artifact

The **grade artifact** is a grader-written JSON object that scores how interesting or useful one episode is.

## Producer

The [grader role](../roles/GRADER.md) writes one JSON file to `COGAME_GRADE_URI`. Graders consume an
[episode bundle](EPISODE_BUNDLE.md) and emit a compact ranking signal for humans, agents, or automated triage.

## Contract

```json
{
  "grader_id": "among-them-grader",
  "score": 0.85
}
```

Fields:

| Field | Required? | Purpose |
| --- | --- | --- |
| `score` | required | Floating-point grade. Range and meaning are grader-defined unless a specific grader documents otherwise. |
| `grader_id` | recommended | Grader self-identification, conventionally matching the runnable id in `manifest.grader[]`. |

Additional grader-specific fields may be included. Consumers should ignore fields they do not recognize.

## Interpretation

Grade scores are not inherently comparable across different graders. A game-specific grader should document its scale in
its role description or implementation docs. A future platform-level normalization rule may tighten this, but the current
cross-game contract only requires a numeric `score`.

Graders are not required to produce identical scores across runs, but deterministic graders make episode ranking,
caching, and tests easier.

## Relationship To Bundles

Grades consume episode bundles, but grade outputs are not currently included in the episode bundle. If diagnosers or
optimizers need grade outputs, those outputs are passed separately today.

## See Also

- [Grader role](../roles/GRADER.md) for invocation.
- [Episode bundle](EPISODE_BUNDLE.md) for grader input.
- [Report](REPORT.md) for the complementary human-readable artifact.
