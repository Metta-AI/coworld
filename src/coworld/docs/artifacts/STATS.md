# Coworld behavior statistics

`coworld.stats.v1` is a reporter JSON contract for behavior and outcomes extracted from recorded episodes. It preserves
metric definitions, opportunities, policy identities, and unavailable measurements across games. Games own the meaning
of their metrics. A stats block is evidence, not a reward function or a claim of policy strength.

Declare a reporter output named `stats`, with type `json` and schema
`https://softmax.com/api/observatory/v2/reporters/schemas/coworld.stats.v1.json`. The schema is publicly downloadable.
The Python models live in `coworld.stats`; an installed CLI can print it offline:

```sh
coworld stats schema
coworld stats validate stats.json
coworld reporters list --schema https://softmax.com/api/observatory/v2/reporters/schemas/coworld.stats.v1.json --json
```

Existing Coworld manifests can reference a compatible reporter through their `reporter` entries. Describe the supported
game/build and replay format in the reporter's description. Consumers discover the declared schema before requesting a
run, then read the returned metric registry to determine coverage. Use pinned reporter versions for reproducible
extraction.

## Measurements and missing evidence

The block requires `schema_version: "coworld.stats.v1"` and contains successful `episodes` and `failures`. It must
contain at least one entry. An episode cannot occur twice or appear in both lists. Each successful episode has its own
provenance, metric definitions, and seats. Every seat reports each registered metric exactly once. Matching metric IDs
and versions must have identical definitions across the block.

Metric categories are `direct`, `opportunity_dependent`, and `outcome`. Direct measurements describe actions or
execution, with that distinction stated in the definition. Opportunity-dependent measurements separate available
opportunities from decisions to use them. Outcomes describe results such as territory or score under the recorded
conditions.

Each metric declares units, eligibility, aggregation, interpretation, and one of three scalar kinds:

- `count`: a nonnegative integer count, with an equal numerical value.
- `rate`: a fraction of eligible opportunities, with integer numerator and positive denominator, equal to
  `count / denominator`.
- `value`: another finite numerical measurement. Use this for ratios that can exceed one.

A rate is bounded by zero and one. Histograms or class frequencies can be expressed as separately defined count/rate
dimensions. Do not relabel incompatible game definitions with the same metric ID and version.

The observation status is explicit:

| Status             | Meaning                                                                                         |
| ------------------ | ----------------------------------------------------------------------------------------------- |
| `measured`         | A finite observation, including a real measured zero                                            |
| `missing`          | Applicable evidence was not recorded or cannot be recovered; includes a reason                  |
| `unsupported`      | The game does not implement the metric; includes a reason                                       |
| `no_opportunities` | A rate with zero eligible opportunities; count and denominator are zero and no value is present |

Do not substitute zero for unavailable measurements. A valid block can contain extraction failures and missing
observations. Consumers must check those fields before using the block for comparisons or learning.

Provenance records the episode and game, replay SHA-256, and extractor version. Game-build and policy-artifact
identities may be explicitly null when unavailable. Context can retain the variant, scenario seed, evaluation protocol,
or other recorded conditions. Missing context does not establish that episodes are comparable.

Replay digests cover the exact consumed bytes, including compression. An unlabelled replay can use
`replay-sha256:<digest>` as its episode identity. Supplied build and policy identities must come from the episode
receipt; replay player names alone do not identify a policy checkpoint.

Both hosted and external reporter submission validate this built-in contract before storage, including numerical
consistency and registry coverage. Arbitrary schema URIs remain producer declarations; the API does not fetch them for
validation. Generated JSON Schema describes structure. Use the Python model or submission endpoint for cross-field
semantic checks.

## Extract a native replay batch

The reference adapter reads complete Paint Arena replays in native JSON, gzip, or zlib format. It reconciles final
results against tile ownership and rejects incomplete tick sequences or mismatched replay digests. The adapter reports
executed movement and territory. Submitted commands remain `missing` because native replays do not retain them.
Purchases remain `unsupported` because Paint Arena has no economy.

Create a JSON list of replay input receipts. Relative paths resolve beside that manifest. For a local native JSON replay
without platform identities:

```sh
python - <<'PY'
import hashlib
import json
from pathlib import Path

path = Path("replay.json")
raw = path.read_bytes()
digest = hashlib.sha256(raw).hexdigest()
replay = json.loads(raw)
receipt = {
    "path": str(path), "episode_id": "replay-sha256:" + digest,
    "game_id": "paintarena", "game_build_id": None, "replay_sha256": digest,
    "policies": [{"id": None, "sha256": None} for _ in replay["player_names"]],
    "context": {},
}
Path("inputs.json").write_text(json.dumps([receipt], indent=2) + "\n")
PY
coworld stats extract-paintarena inputs.json output --workers 4
coworld stats validate output/stats.json
```

Append more receipts to extract multiple episodes. The command writes immutable successful episode records under
`episodes/`, plus immutable batch snapshots under `batches/`, a current `stats.json`, and a script-free `report.html`.
Batch snapshots retain earlier failures when a later invocation succeeds. Repeated invocations reuse successful records
after checking their source identities. Changed inputs require a new output directory. Per-replay failures remain
visible and produce exit code 1 after rendering available evidence. Interrupted batches can resume from already-written
episode records.

Receipt provenance is validated for the entire manifest before extraction starts. Invalid identities reject the manifest
without creating output artifacts; failures reading or extracting a valid receipt remain per-replay failures.

Keep input receipts and replays separate from the reserved `stats.json`, `report.html`, `episodes/`, and `batches/`
output paths. The command rejects overlaps before writing artifacts.

The command requests a browser preview by default. `--no-open` supports headless execution; `BROWSER` can select a
host's browser-opening command. A missing preview leaves the HTML artifact available. The reference table shows episode
seats and the three control categories. Cross-policy aggregation, reference selection, anomaly thresholds, and training
utilities belong to the consumer; the extractor does not infer a leaderboard or label behavior as deficient.

## Publish through reporters

A native extractor in Nim or another language can emit the same JSON without adopting Python. Register an external
reporter with the `stats` declaration and a `comparison` part of type `render-html`. Submit each part through the
existing reporter output API, using the reporter key for publication. Replay reads use the operator's normal data
credentials. See the [reporter role](../roles/REPORTER.md).

A hosted reporter can read several episodes through its tool interface and emit one batch stats block. Hosted components
target the current reporter WIT world. A native executable cannot run inside that sandbox without a supported component
build.

External reporter outputs are visible to authenticated users and have no platform run trace. Keep private training
evidence local or use a hosted run with the appropriate access rules. HTML parts must follow the
[safe render profile](RENDER.md): self-contained styles and assets, with no scripts. Interactive comparisons can consume
the JSON in a separate application.
