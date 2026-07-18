# AGENTS.md — Crewrift / Coworld player-optimizer learning package (jboggs)

Use this package when improving a Coworld player policy (crewrift/crewborg especially) or
designing reusable optimizer guidance from Coworld work. It is layered into orthogonal tiers —
load the one that matches your task:

- **crewrift-specific/** — only-true-with-crewrift social-deduction lessons (roles, suspicion, voting,
  kills/vents, the Sprite-v1 protocol). Carries the concrete `LOOP.md` and `performance/LOG.md`.
- **optimization-loop-specific/** — the hypothesis-driven A/B optimization loop over a *scripted*
  Coworld policy, plus the nightly data-science refit. Game-agnostic across Coworlds, NOT general dev advice.
- **generic/** — true for any software / coding-agent / research work.
- **universal/** — all of the above blended (source of truth for re-runs); its `AGENTS.md` is the full
  always-on lesson set.

Start from evidence. Before changing a policy, inspect completed hosted experience requests, league
replays, policy trace logs, or a focused local reproduction until one concrete failure is named. Local
runs are smoke/diagnosis only; promotion needs completed hosted evidence (see `LOOP.md`).

Change one thing per cycle and A/B it against the prior best on matched experience requests; never let
'uploaded' or 'request created' masquerade as evidence. League submission is the irreversible, human-gated step.

Session-derived lessons are marked ⚠ _unverified_ — treat them as candidates, not established fact.
