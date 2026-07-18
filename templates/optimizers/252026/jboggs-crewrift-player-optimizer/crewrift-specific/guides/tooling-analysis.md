# Tooling & analysis — guide (crewrift tier)

Reference notes, design rationale, and negative results (3).

#### 1. Check replay version provenance before blaming the parser; keep replay semantics in the Nim tool
`crewrift` · **negative result** · ⚠ _session-derived, unverified_

When a replay fails to parse, extract game.version and the game image digest from the episode spec and compare against the coworld_manifest.json version of the local crewrift checkout you built the helper from -- a mismatch (live replays at crewrift 0.1.48 vs origin/master manifest 0.1.40) means the replays are NEWER than any buildable source and no rebuild helps (hours were wasted rebuilding before checking). Do not reimplement crewrift replay parsing in Python: the structured event layer lives in tools/expand_replay.nim; add a JSONL machine-output mode there and have Python consume it.
  <sub>sources: codex:019eb326-beb5-7b03-890e-732da6aa6746, claude-code:ef964049-4e16-4c32-b7f1-32871349d20a</sub>

#### 2. Consume replays/stats via structured JSONL/parquet, never by reverse-parsing human text
`crewrift` · **negative result** · tool: `expand_replay`

Do NOT reverse-parse a replay/stats tool's human TEXT output (each line type needs a bespoke regex that re-derives structure the simulator already computed, drops fields like real slot ids, and rots whenever the format changes). Use the tool's structured machine-output mode for all consuming tooling. For Coworld games this is the shared stats schema -- {ts, player, key, value} rows (ts int64 tick, player int16 slot with -1 for global facts, key string event name, value JSON-encoded string, one JSON doc per row), available as a JSONL array or a four-column parquet; keys/values are author-defined per game, and for relational events about two players use player=-1 and pack both slots into the JSON value rather than emitting one row per player. If the structured mode does not exist yet, add it to the existing tool (e.g. a JSONL mode in the Nim expander) rather than reimplementing the parsing in a downstream language.
  <sub>sources: claude-code:10f74020-e0e6-4515-8d0c-f071d41766ad, claude-code:c24c7575-fe83-4650-952b-e1817c930d01, coworlds/coworld-crewrift/docs/designs/expand-replay-reporter.md, claude-code:2e0ca80b-d747-4358-a5dc-650397742760 (+1)</sub>

#### 3. Crewrift button-runner interception corpus (1,875 games, croatoan)
`crewrift`

Corpus analysis of Crewrift button-runners (1,875 games, map croatoan): the prior-meeting gap clusters at 800-1000 ticks (median 945); runners travel essentially alone (median 0 other crew within 48px the whole approach); ~58% of interceptable runners funnel through one off-bridge chokepoint (the Bridge<->Hydroponics corridor mouth, ~x270-410/y270-410, ~150-280px east of the button); and ~42% are already in the bridge 250 ticks out and not worth camping for.
  <sub>sources: personal_labs/crewrift_lab/crewrift/crewborg/docs/designs/button-runne</sub>
