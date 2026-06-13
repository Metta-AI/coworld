# AGENTS.md - CrewRift Player Optimizer

Use this package when improving a CrewRift player policy or designing reusable
optimizer guidance from CrewRift work.

Start from evidence. Before changing a policy, inspect completed hosted XP,
completed live rounds, replay artifacts, policy logs, or a focused local
reproduction until one concrete failure is named.

Keep the policy lane explicit. Richard Higgins and RelhAlpha are separate
player identities. Record which policy lane is active, which lane is protected,
and which policy version is actually owned by the intended player before
uploading or submitting.

Do not treat slots as strategy. In CrewRift, runner slots are protocol metadata
for connection, UI parsing, exact reproduction, and result indexing. Role and
strategy state come from observations, results, and the game source.

Separate diagnostic gates from promotion gates. Local episodes and replay
summaries are for diagnosis and smoke checks. Promotion requires completed
hosted evidence against relevant current opponents, plus artifact inspection.

Record every candidate state. A candidate can be built, uploaded no-submit,
XP-requested, XP-completed, rejected, held, or promoted. Do not let "uploaded"
or "request created" masquerade as evidence.

Keep bulky or private artifacts out of the learning package. Store compact
lessons, source paths, IDs, and decisions. Paraphrase session-derived lessons
and mark weak provenance in manifests.
