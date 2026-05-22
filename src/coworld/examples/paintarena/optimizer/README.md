# Paint Arena Reference Optimizer

The PaintArena optimizer is a small runnable reference for the Coworld optimizer role. It reads a Coworld manifest plus
optional prior report, grader, and diagnoser artifact URI lists, then writes a deterministic JSON optimization plan.

Required environment:

- `COWORLD_MANIFEST_URI`: JSON Coworld manifest.
- `COGAME_OPTIMIZER_ID`: manifest role id for this optimizer.
- `COGAME_OPTIMIZER_OUTPUT_URI`: JSON output destination.

Optional environment:

- `COGAME_POLICY_WORKSPACE_URI`: policy workspace to inspect or modify.
- `COGAME_REPORT_URIS`: comma-separated report artifact URIs.
- `COGAME_GRADER_OUTPUT_URIS`: comma-separated grader output artifact URIs.
- `COGAME_DIAGNOSER_OUTPUT_URIS`: comma-separated diagnoser output artifact URIs.
