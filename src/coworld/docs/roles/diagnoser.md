# Diagnoser Role

**Status:** reserved

> **The diagnoser contract is highly tentative.** This document describes the current best-guess shape, but the design
> is expected to change significantly as concrete use cases land. Multiple load-bearing pieces — how the target policy
> is identified, single-episode vs multi-episode input, output structure — remain explicit open questions. Treat this
> doc as a starting point for discussion, not a stable contract.

## What it does

The diagnoser role evaluates a target policy using episode evidence and emits policy-facing advice or assay results.
Diagnosers are the canonical Coworld home for a battery of policy tests — "this policy does X with Y skill" across many
X/Y dimensions — that help a coding agent or a researcher understand why a policy behaved the way it did and what to
change next.

The key distinguishing input compared to reporters: diagnosers take a target policy as input alongside episode
artifacts. Reporters explain what happened in an episode; diagnosers evaluate a specific policy's behavior in that
episode and emit guidance about the policy itself.

## Where it lives in the manifest

`manifest.diagnoser[]`, with `type: "diagnoser"` on every entry. The section is required, but the array may be empty
while the role is reserved. See [`MANIFEST_README.md`](../../MANIFEST_README.md) for the full runnable shape.

## Contract (highly tentative)

A diagnoser runnable is a short-lived, process-style container started by a CLI or platform action that wants advice
about a particular policy's behavior in a particular episode. It does not expose HTTP routes or websockets.

### Input

A diagnoser receives at least these env vars:

- `COGAME_EPISODE_BUNDLE_URI` — URI of a `.zip` file containing the episode's artifacts. Same bundle shape that
  reporters and graders receive. See [`EPISODE_BUNDLE_README.md`](../../EPISODE_BUNDLE_README.md).
- `COGAME_TARGET_POLICY_URI` — URI of, or reference to, the target policy this run should evaluate. The exact format of
  this reference (policy image, policy version ID, checkpoint URI, etc.) is **not yet defined**; see
  [Open questions](#open-questions).

### Output

A diagnoser writes its output to one env var:

- `COGAME_DIAGNOSIS_URI` — URI where the diagnoser writes a single `.zip` containing all diagnosis files.

The output zip is structured similarly to a reporter's output, with an optional `manifest.json` at the root identifying
renderable and structured files. The exact required and optional fields for diagnoser `manifest.json` are not yet
defined.

### Execution

Diagnosers are on-demand. They are **not** run automatically by the episode runner.

A diagnoser run is triggered by a CLI command (planned: `coworld run-diagnoser` — exact shape TBD), a hosted button, or
an automated pipeline. The invoker is responsible for assembling the input bundle, identifying the target policy, and
consuming the output.

## Open questions

The diagnoser role has many unresolved design questions. They are listed here so future work knows where the
load-bearing decisions still live.

- **Target policy reference format.** `COGAME_TARGET_POLICY_URI` is currently a placeholder. The reference might point
  at a Docker image ref, a policy version ID, a checkpoint archive, or something else. The right answer depends on
  whether the diagnoser needs to _run_ the policy itself or just _inspect its behavior_ via the replay in the bundle.
- **Single-episode vs multi-episode input.** Some diagnoses ("did this policy avoid the wall?") work fine over a single
  episode. Others ("does this policy generalize?") need many. Whether the contract supports multi-episode input — and if
  so, how — is undefined.
- **Output structure.** Reporters' `manifest.json` defines `render` and `event_log` fields. Diagnoser output is likely
  richer (advice, structured findings, suggested code changes) and probably needs its own field vocabulary that has not
  been written yet.
- **Interaction with reporters and graders.** A diagnoser may want to consume already-produced reporter output or grader
  scores when forming its advice. The bundling layer does not currently surface prior supporting-runnable output; if
  diagnosers need it, the bundle contract has to be extended.
- **Determinism.** Same shape as reporter and grader, but the policy-evaluation aspect may make non-determinism more
  common (e.g., diagnosers that re-run the policy under different conditions).

## How it fits with other roles

Diagnosers live in the post-episode artifact layer alongside reporters, graders, and optimizers. They are the only
supporting role whose primary subject is the policy rather than the episode — the bundle is evidence, but the diagnosis
is about the policy. Diagnoser output feeds two main downstream surfaces:

- Coding agents and researchers iterating on a policy use diagnosis advice as a directed signal for what to change.
- Optimizers may consume diagnoser output as part of their input when iterating on policies algorithmically. The
  specifics of this pipeline are not yet defined.

See [`OVERVIEW.md`](OVERVIEW.md) for the full artifact flow.

## See Also

- [`EPISODE_BUNDLE_README.md`](../../EPISODE_BUNDLE_README.md) — bundle contract the diagnoser's episode input follows.
- [`MANIFEST_README.md`](../../MANIFEST_README.md) — manifest field reference for `manifest.diagnoser[]`.
- [`COWORLD_README.md`](../../COWORLD_README.md) — Role Status framework, runnable conventions.
- [`reporter.md`](reporter.md), [`grader.md`](grader.md), [`optimizer.md`](optimizer.md) — sibling supporting runnables.
- [`OVERVIEW.md`](OVERVIEW.md) — full artifact flow.
