# Optimizer Role

**Status:** reserved

> **The optimizer role has a fundamentally different shape from the other supporting runnables.** Where reporter,
> grader, and diagnoser are short-lived process-style containers that consume an episode bundle and emit a single output
> artifact, the optimizer is a long-running workbench: a developer "opens" the optimizer for a Coworld and uses it
> interactively to drive a policy-improvement loop. The contract below reflects this difference. The design is under
> active development; expect changes as the workbench shape stabilizes.

## What it does

The optimizer role is the workbench through which a developer (human or agent) iterates on a policy for a given Coworld.
The canonical implementation, [`Metta-AI/optimizers`](https://github.com/Metta-AI/optimizers), is a local Next.js
application that integrates with the Coworld CLI to run episodes, inspect replays, coordinate agent tasks, edit policy
source, and evaluate candidate policies against a champion.

Unlike reporter, grader, and diagnoser, an optimizer is not a one-shot job. It is opened, used over a session
(potentially many hours and many episodes), and closed. Its "output" is not a single artifact file but a series of side
effects: policy workspaces, candidate policy versions, comparison evaluations, and ultimately a new policy version
uploaded via `coworld upload-policy`.

## Where it lives in the manifest

`manifest.optimizer[]`, with `type: "optimizer"` on every entry. The section is optional in the current schema, but
intended to become required once the role is no longer reserved. See [`COWORLD_MANIFEST.md`](../COWORLD_MANIFEST.md) for
the full runnable shape.

When an optimizer entry declares a GitHub `source_url`, point it at the implementation source, not only a docs folder.
`coworld certify` checks that the source has non-empty contents and that a Dockerfile exists at that path or an ancestor
build root.

## Contract (tentative)

An optimizer runnable is a long-running workbench image. The invoker opens it for a Coworld; the workbench hosts the
policy-improvement loop until the user closes it.

### Invocation

An optimizer is opened with a CLI command (planned: `coworld open-optimizer` — exact shape TBD) or directly via
`docker run`. The optimizer container exposes a web UI; the developer connects to it (typically through a browser) and
works in the workbench.

The mechanism for passing Coworld context (manifest reference, initial policies, initial episodes) into a freshly opened
optimizer instance is not yet defined.

### Inputs

The optimizer needs at least:

- a reference to the Coworld being optimized (manifest path or `coworld_id`);
- optionally, initial policies to load into a workspace;
- optionally, episode references to seed the workbench with.

Whether these arrive as env vars, CLI args, mounted config files, or some combination is not yet locked.

The optimizer does not currently define a standard `COGAME_EPISODE_BUNDLE_URI` input, but an optimizer workbench may load
episode bundles as seed evidence; see [`artifacts/EPISODE_BUNDLE.md`](../artifacts/EPISODE_BUNDLE.md).

### Outputs

Optimizer outputs are side effects and optional workbench artifacts, not one standardized output file; see
[OPTIMIZER_OUTPUTS.md](../artifacts/OPTIMIZER_OUTPUTS.md).

### Execution

Optimizers are interactive and long-running. They are **not** run automatically by the episode runner or any batch
pipeline; they are opened by a user (or an agent acting on a user's behalf) when policy iteration is the goal.

## Open questions

- **Invocation contract.** What env vars, CLI args, or config files convey "you are optimizing for this Coworld,
  starting from these policies, with these episodes already loaded"? Not yet defined.
- **Game-agnostic vs game-specific optimizers.** The canonical `Metta-AI/optimizers` is intentionally game-agnostic. A
  specific Coworld might want to ship a game-specific optimizer image that bundles game-aware tooling. How a
  game-specific optimizer composes with (or replaces) the default is not yet defined.
- **Output handoff to the platform.** Today a candidate policy reaches the platform via `coworld upload-policy` run by
  the user. Whether there is a more direct optimizer → platform handoff in the future (e.g. the optimizer itself pushing
  policy versions) is undefined.
- **Multi-Coworld instances.** Can one optimizer instance host multiple Coworlds at once? The canonical implementation
  today does; the role-level contract has not been written.

## How it fits with other roles

The optimizer is the rightmost node in the Coworld supporting-runnable flow — it ingests episode evidence and, in
principle, reporter renders, grader rankings, and diagnoser advice, and turns them into policy improvements. In practice
today, the optimizer pulls episode artifacts directly via the Coworld CLI and produces
[optimizer outputs](../artifacts/OPTIMIZER_OUTPUTS.md) such as candidate workspaces, evaluation runs, and uploaded
policy versions.

See [`README.md`](../README.md) for the full artifact flow, and
[`Metta-AI/optimizers`](https://github.com/Metta-AI/optimizers) for the canonical optimizer implementation.

## See Also

- [`Metta-AI/optimizers`](https://github.com/Metta-AI/optimizers) — canonical game-agnostic optimizer implementation
  (Next.js workbench, Postgres + pgvector, agent coordination, replay debugger).
- [`artifacts/EPISODE_BUNDLE.md`](../artifacts/EPISODE_BUNDLE.md) — episode artifact package an optimizer may load as
  seed evidence.
- [`artifacts/OPTIMIZER_OUTPUTS.md`](../artifacts/OPTIMIZER_OUTPUTS.md) — side effects and optional workbench artifacts
  produced by this role.
- [`artifacts/REPORT.md`](../artifacts/REPORT.md), [`artifacts/GRADE.md`](../artifacts/GRADE.md), and
  [`artifacts/DIAGNOSIS.md`](../artifacts/DIAGNOSIS.md) — supporting-role outputs an optimizer may consume.
- [`COWORLD_MANIFEST.md`](../COWORLD_MANIFEST.md) — manifest guide and generated-schema pointer.
- [`README.md`](../README.md) — role status framework, runnable conventions, and artifact flow.
- [`REPORTER.md`](REPORTER.md), [`GRADER.md`](GRADER.md), [`DIAGNOSER.md`](DIAGNOSER.md) — sibling supporting runnables;
  note the optimizer's shape differs.
