# Diagnosis Artifact

The **diagnosis artifact** is the diagnoser-written output for policy-facing advice or assay results.

## Status

The diagnosis contract is reserved and highly tentative. The role exists so Coworlds have a home for policy tests and
actionable advice, but the exact output manifest shape is not stable yet.

## Producer

The [diagnoser role](../roles/DIAGNOSER.md) writes one zip to `COGAME_DIAGNOSIS_URI`. A diagnoser consumes an
[episode bundle](EPISODE_BUNDLE.md) plus a target policy reference and emits advice about that policy's behavior.

## Expected Shape

The current expected shape mirrors reports at a high level:

- one zip per diagnoser run;
- optional top-level `manifest.json`;
- renderable files for humans or agents;
- structured files for machine-readable findings, assays, or suggested next actions.

The required `manifest.json` fields are not defined yet. Do not build downstream systems that depend on diagnosis zip
layout without first stabilizing this contract.

## Relationship To Bundles

Diagnoses consume episode bundles, but diagnosis outputs are not currently included in the episode bundle. If an optimizer
needs diagnosis output, it receives diagnosis artifact URIs separately today.

## See Also

- [Diagnoser role](../roles/DIAGNOSER.md) for invocation and open questions.
- [Episode bundle](EPISODE_BUNDLE.md) for diagnoser input.
- [Event log](EVENT_LOG.md) for structured reporter evidence that diagnosers may use.
- [Optimizer outputs](OPTIMIZER_OUTPUTS.md) for downstream policy-improvement artifacts.
