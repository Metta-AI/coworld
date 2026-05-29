# Optimizer Outputs

**Optimizer outputs** are the artifacts and side effects produced while improving a policy for a Coworld.

## Status

The optimizer role is reserved and has a different shape from reporter, grader, and diagnoser. It is a long-running
workbench rather than a one-shot artifact writer, so there is no single stable cross-game output contract yet.

## Producer

The [optimizer role](../roles/OPTIMIZER.md) may produce:

- candidate policy workspaces;
- candidate policy versions uploaded through `coworld upload-policy`;
- evaluation results comparing candidates against champions or baselines;
- task documents, comments, attachments, and run transcripts in the workbench;
- optional plan artifacts for simple reference optimizers.

The Paint Arena reference optimizer writes a JSON plan to `COGAME_OPTIMIZER_OUTPUT_URI` with `optimizer_id`,
`coworld_name`, `policy_workspace_uri`, `input_counts`, and `recommendations`. That is a useful reference implementation,
not a finalized cross-game optimizer contract.

## Inputs

An optimizer may load [episode bundles](EPISODE_BUNDLE.md), [reports](REPORT.md), [grades](GRADE.md), and
[diagnoses](DIAGNOSIS.md) as seed evidence. Today these inputs are usually pulled through Coworld tooling or passed as
artifact URI lists rather than through one standard optimizer input env var.

## Handoff

The platform does not consume optimizer output through the same standard env-var artifact contract used by reporter and
grader. A candidate policy leaves the optimizer through the normal policy-upload flow.

## See Also

- [Optimizer role](../roles/OPTIMIZER.md) for the workbench contract.
- [Episode bundle](EPISODE_BUNDLE.md) for episode evidence.
- [Report](REPORT.md), [grade](GRADE.md), and [diagnosis](DIAGNOSIS.md) for supporting-role inputs.
