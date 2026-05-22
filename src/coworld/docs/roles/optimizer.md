# Optimizer Role

Optimizers are game-agnostic improvement apps. They target a Coworld plus an optional policy workspace, ingest useful
reporter artifacts, diagnoser output, replay/results, stats parquet, and game/protocol docs or markdowns, and drive
local policy iteration.

The optimizer can decide which reports, grades, and diagnoser outputs to ingest. It should stay game-agnostic at the
orchestration layer: game-specific behavior should enter through game docs, reporter/diagnoser artifacts, grader scores,
plugin adapters, or policy templates rather than hard-coded assumptions in the core optimizer.

Runtime contract:

- receive `COWORLD_MANIFEST_URI`, a JSON Coworld manifest;
- receive `COGAME_OPTIMIZER_ID`, the selected manifest role id;
- receive `COGAME_OPTIMIZER_OUTPUT_URI`, where the optimizer writes its output artifact;
- optionally receive `COGAME_POLICY_WORKSPACE_URI`, a policy workspace to inspect or update;
- optionally receive comma-separated artifact lists in `COGAME_REPORT_URIS`, `COGAME_GRADER_OUTPUT_URIS`, and
  `COGAME_DIAGNOSER_OUTPUT_URIS`.

The output artifact is runner-owned. For the reference flow, it is a deterministic JSON optimization plan that names the
target Coworld, counts the supplied evidence artifacts, and records the concrete next policy-iteration steps.
