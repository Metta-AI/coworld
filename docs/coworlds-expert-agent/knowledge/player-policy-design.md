# Player Policy Design

## Start with orientation

The starting point for a player policy is making sure the player has the background context — the base world model — that from the first moment allows its decisions to be made in an oriented way.

Before any architecture or skill system, give the player:
- What kind of world this is and how it works
- What success looks like (what matters, what it's trying to do)
- What the rules of interaction are (what will be accepted, what will be refused)
- Its own identity and orientation toward the world (persona)

An oriented player makes good decisions from turn 1. An unoriented player with a sophisticated architecture still flails.

## Trust the LLM with full context

Given the right context (persona + game rules + memory + current observation), the LLM makes better action choices than any heuristic selector. Heuristics that override the LLM's choice bottleneck persona expression and produce rigid, suboptimal behavior.

What fails: hardcoded action sequences ("after venture → tap, after tap → develop"). These enforce rigid pacing regardless of what the persona or situation calls for.

What works: give the LLM the persona + game rules + memory + observation and let it choose its own action. The model naturally adapts pacing to persona and context.

## Persona shapes behavior through context, not code

A persona is a description that goes in front of every prompt, shaping how the LLM interprets the situation. The same game rules + memory system produces radically different play patterns depending on the persona:

- A gardener taps for soil quality, develops by planting, stays deep in one place
- An explorer taps for directions and signs of habitation, ventures at every opportunity
- A philosopher develops abstract structures, upkeeps to consolidate meaning

All use the same code path, same memory system, same action space. The persona text does all the work.

## Memory is the key differentiator

What separates a good player from a bad one is what it tracks and remembers:
- What's been established vs. what was refused
- Cross-location connections and patterns
- Goals and progress toward them
- The model of the world it's building over time

A player with memory and full context dramatically outperforms one with a sophisticated action-selection heuristic but no memory.

### Memory design

A simple `remember(scope, text)` tool where:
- `scope = "world"` → notes visible everywhere
- `scope = location_id` → notes visible only in that location

The player decides what to remember. Good guidance for what to note:
- Facts the world confirmed (things you can build on)
- What was refused and why (don't repeat)
- Connections between locations
- Goals and theories being tested

## Optimizing player policies

Don't micromanage heuristics ("venture more often", "upkeep after N events"). Instead:

1. Run episodes and read the transcript
2. Look at specific decisions that went wrong
3. Identify what was observable that the player missed, or what it should have been tracking in memory
4. The fix is usually: surface the right information (in persona, game rules, or memory), not add more rules

The pattern: understand what context was missing → provide it → trust the model to use it well.
