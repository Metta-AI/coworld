# AGENTS.md - Universal CrewRift Optimizer Learnings

Use evidence gates, not variant churn. A useful candidate connects observed
failure, source correction, measured behavior, and promotion decision.

Keep identity and policy source explicit. A policy version must be rebuildable
from shared source and owned by the intended player before it can be treated as
a durable optimizer result.

Treat metadata as metadata until proven otherwise. Position, slot, runner
assignment, request ID, image ID, and policy version ID help reproduce and
measure behavior; they are not strategic state by themselves.

Use one loop state machine across tools: diagnosed, patched, locally checked,
uploaded no-submit, XP requested, XP completed, artifacts inspected, promoted
or held.

Make every improvement claim falsifiable. The claim should name the failure,
the owner changed, the metric or behavior expected to move, and the evidence
that would reject it.

Record negative and incomplete outcomes. Rejected hypotheses, underfilled
requests, partial artifact downloads, player-identity mistakes, and no-XP
uploads are reusable knowledge.
