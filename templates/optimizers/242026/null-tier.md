# Null tier — source material deliberately NOT packaged

These haul/source files were reviewed during the routing pass and **deliberately
left out** of the `universal/` package. Each one was judged to carry no durable,
positive payload that isn't already covered by a routed item — so packaging it
would only add a "do-not-read" pointer or duplicate content that lives elsewhere.

This is not a reject pile of unread files: every entry below was read, its gist
recorded, and the omission justified. (The harness's own `_dropped.json` under
`haul/from-sessions/` is a separate thing — that is the extraction harness's
pre-routing reject list, not a learning, and is neither routed nor cut here.)

Total cuts: **1**.

---

## `haul/from-files/extracted/game-docs-are-empty-stubs.md`

**Content gist:** A pure negative marker documenting that the six
`haul/from-files/docs/game-*.md` files (`game-rules.md`, `game-sprite_v1.md`,
`game-optimizer.md`, `game-player.md`, `game-play_crewrift.md`, `game-submit.md`)
are 0-byte / header-only stubs — their source files under
`/Users/daveey/code/crewrift/_docs/` have been empty since first commit
(`26a031f`), so the doc-capture pipeline harvested filenames with no content
underneath. Its only constructive payload is a redirect: for the real
game-model / Sprite-v1 protocol / parity / scoring facts those stubs *promise*,
go instead to the Nim source (`global.nim`, `sim.nim`) or the project memory
notes (`crewrift-parity-win-model`, `crewrift-league-score-model`).

**Why cut:** The redirect it offers is already implied by every guide that grounds
its game-model claims in `sim.nim` / `global.nim` (e.g. `crew-strategy-and-open-levers`
cites `sim.nim:3333` parity, `global.nim:2194` ghost arrows; the AGENTS.md scoring
section cites `sim.nim checkWinCondition`). The parity/score facts the stubs were
*supposed* to summarize are fully captured in the routed
`crewrift-parity-win-model` / `crewrift-league-score-model` content. Carrying this
file forward would package a standalone "these six other files are empty, don't
read them" pointer — a do-not-read marker with no positive content of its own. The
empty stubs it warns about were themselves never packaged, so the warning has no
referent inside `universal/`.
