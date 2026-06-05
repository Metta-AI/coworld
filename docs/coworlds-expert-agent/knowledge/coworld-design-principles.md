# Coworld Design Principles

## The derivation chain

Everything in a coworld derives from one question: what does "good" mean in this game?

```
Game (defines "good")
  → Player policy (tries to be good)
    → Optimizer (helps a human + agent get better at it)
      → Graders + Reporters (the optimizer's sensory organs)
```

Design backward from what "good" means, through the optimizer, down to the graders and reporters. Never design graders in isolation — they exist to serve the optimizer.

## The optimizer is the center of gravity

The game developer delivers a player policy AND an optimizer for that player policy. The optimizer wants some set of tools (graders and reporters) — that set is what the developer should provide.

The optimizer is human-in-the-loop tooling. Autoresearch barely works for closed-ended verified-reward games; it doesn't work in multiagent/multipolicy settings. The optimization loop is: watch replays, investigate features, run stats reports, make changes at human direction.

## Graders are perspectives, not truth

A grader is success according to someone, for some purpose. The same episode gets different scores depending on what question you're asking and whose perspective you're evaluating from.

The upstream schema names slots for questions (purposes). The game developer's job is to figure out which questions make sense for their game. Almost every game needs:

- "Who won?" — Match scoring. The tournament ranking signal.
- "Which episodes should I learn from?" — Expected advantage/surprisal. Scores high when novel things happen, when there's surprisal vs. the model. The idea: develop your own sense of what's valuable, trust that it'll eventually produce game-winning play.
- "Where in this episode should I look?" — Interest-range marking. Which part of this episode deserves human attention (turn ranges, not individual turns).
- "Given goal X, how much progress toward X?" — Conditional progress. For evaluating conditioned policies.
- "How does this compare to my recent batch?" — Relative normalization.

But the real answer is always: whatever the optimizer needs.

### The basketball analogy

In basketball what matters is the ball going through the hoop, but game tape of basketballs through hoops isn't interesting — it's everything leading up to that. The "points scored" grader ranks matches; the *interesting* graders help you understand the play that led to the score.

## Reporters serve human comprehension

Reporters exist because humans need to *see* what happened before they can improve. Useful views:

1. **Full-resolution transcript** — read the episode like a story at full detail. The base unit of visibility.
2. **God's-eye world summary** — the whole world from above, like a condensed encyclopedia. Pyramid-style: overview first, then iteratively expanded granularity. Can be long if there's material.
3. **World-graph visualization** — visual of the world topology + location visuals. Activates human visual-scan capacity to detect anomalies. Animated over time is ideal.
4. **Agent-thinking view** — two-column layout: what the agent saw AND what it was *thinking* as it was deciding. Not just interactions, but the reasoning.
5. **Belief comparison** — what does the agent know/believe about the state of the world vs. what does the world believe about itself? God's-eye belief state.
6. **Key-mechanic overlay** — the lifecycle of whatever the game's core mechanic is (sparks, scores, resources, alliances) overlaid on whichever view. Important but gets layered on top, not shown alone.

## The diagnoser tests mechanical competence

Authored scenarios that exercise specific skills. Unit tests for player policies.

- Start simple (basic action competence at different difficulty levels)
- Setups can be realistic or artificial — they test different things
- NOT optimizable — training against diagnostics immediately overfits and ruins them

## Platform vs. game developer

The platform provides mechanism and required shape. The coworld developer provides the baselines that "just work" for their game. The schema requires coverage; the developer chooses implementation.

## Common mistakes

1. **Designing graders independently of the optimizer.** Every grader should have a named consumer.
2. **Treating PRD purpose slots as a checklist.** The slots name structural questions; fill them based on what *your* optimizer needs.
3. **Building automated RL signals for a human-in-the-loop process.** If optimization is human-directed, build things humans can read and act on.
4. **Confusing "what happened" with "what's valuable."** Reporters tell you what happened. Graders tell you what's valuable. Different questions.
5. **Forgetting that the game defines "good."** The game is the gold standard. Everything else serves getting better at the game.
6. **Jumping to implementation before understanding the core idea.** Slow down. Pay attention to the underlying cross-coworld pattern, not just the specific game's needs.

## The viability test

A coworld is viable when: a human downloads the starter package, improves their policy with their coding agent guided by the optimizer's tooling, verifies locally, uploads, and the tournament confirms it. Then they do it again.
