# Coworlds Expert Agent

A Claude Code agent that knows how to design and build Softmax Coworlds — game architecture, player policies, runnables, and optimization loops.

## What it knows

- **Design principles** — the derivation chain (game → optimizer → graders/reporters), grader philosophy, common mistakes
- **Player policy design** — orientation-first, trust the LLM, persona through context, memory as key capability
- **Schema contracts** — manifest fields, role contracts, artifact formats, env vars
- **Collaboration patterns** — understand before implementing, trace derivation chains, interview before proposing

## Install

Copy the agent definition into your project's `.claude/agents/` directory:

```bash
cp coworlds-expert.md /path/to/your-coworld/.claude/agents/
cp -r knowledge/ /path/to/your-coworld/.claude/agents/coworlds-expert-knowledge/
```

Or symlink for easy updates:

```bash
ln -s /path/to/metta/packages/coworld/docs/coworlds-expert-agent/coworlds-expert.md \
  /path/to/your-coworld/.claude/agents/coworlds-expert.md
ln -s /path/to/metta/packages/coworld/docs/coworlds-expert-agent/knowledge \
  /path/to/your-coworld/.claude/agents/coworlds-expert-knowledge
```

## Usage

Once installed, the agent is available in Claude Code sessions within your project. Launch it when you need guidance on:
- Designing graders/reporters/diagnosers for your game
- Designing or improving a player policy
- Structuring your manifest for certification
- Understanding what the optimizer needs
- Debugging why your player is making bad decisions

## Files

```
coworlds-expert-agent/
  README.md                              (this file)
  coworlds-expert.md                     (agent definition — copy to .claude/agents/)
  knowledge/
    coworld-design-principles.md         (derivation chain, grader philosophy)
    player-policy-design.md              (orientation, LLM trust, persona, memory)
    coworld-schema-current-state.md      (manifest schema, role contracts)
    working-with-people-on-design.md     (collaboration patterns)
```
