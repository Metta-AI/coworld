# Optimizer Role

Optimizers are game-agnostic improvement apps. They target a Coworld plus an optional policy workspace, ingest useful
reporter artifacts, diagnoser output, replay/results, stats parquet, and game/protocol docs or markdowns, and drive
local policy iteration.

The optimizer can decide which reports, grades, and diagnoser outputs to ingest. It should stay game-agnostic at the
orchestration layer: game-specific behavior should enter through game docs, reporter/diagnoser artifacts, grader scores,
plugin adapters, or policy templates rather than hard-coded assumptions in the core optimizer.
