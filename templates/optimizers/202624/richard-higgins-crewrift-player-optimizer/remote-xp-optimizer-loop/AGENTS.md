# AGENTS.md - co-gas Remote XP Optimizer Loop

The canonical co-gas decision loop is mandate -> diagnose -> source correction
-> candidate YAML -> no-submit hosted policy version -> XP -> artifact review
-> lower-lane replacement or hold.

Start with current live state. Refresh `reports/latest.md`, run the strict
mandate check, and choose the lower owned lane in the failing league. Keep the
higher lane protected.

Use candidate YAMLs as immutable evidence ledgers. They should name artifact
paths, policy version IDs, image IDs, scores, role splits, failure classes, and
the exact decision.

Completed XP is the promotion gate. Pending/running requests, lower-division
coverage, local-only wins, image upload, and no-submit policy creation do not
replace a champion.

If XP rejects a hypothesis, record the hold and form the next candidate from
low artifacts. Do not continue stacked variants without understanding the last
completed result.
