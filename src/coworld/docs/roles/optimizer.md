# Optimizer Role

Optimizers are game-agnostic improvement apps. They target a Coworld plus an optional policy workspace, ingest useful
reporter artifacts, diagnoser output, replay/results, stats parquet, and game/protocol docs or markdowns, and drive
local policy iteration.

The optimizer can decide which reports and diagnoser outputs to ingest. There is no separate canonical debugger or
grader role in the manifest.
