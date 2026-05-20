# Diagnoser Role

Diagnosers consume a target policy and emit policy-facing assay results or advice. They may also consume the Coworld
manifest, replay and results artifacts, reporter outputs, stats parquet, logs, or traces, but the policy input is what
distinguishes them from reporters.

The diagnoser contract is the canonical Coworld home for a battery of policy tests: "your policy does X with Y skill"
across many different X/Y checks. It is suitable for prompts or runnable services that help a coding agent understand
why a policy behaved the way it did and what to improve next.

Reporters explain episode experience. Diagnosers evaluate a policy using that experience and any additional local assays.
