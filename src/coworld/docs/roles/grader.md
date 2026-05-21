# Grader Role

Graders score how interesting or useful an episode was from the game creator's perspective. They consume replay/results
artifacts and emit a scalar ranking signal.

The grader contract is intentionally smaller than the reporter contract. Reporters produce human-readable or
machine-dense explanations of experience; graders produce a compact score that can help choose which episodes deserve
attention, promotion, or follow-up analysis.
