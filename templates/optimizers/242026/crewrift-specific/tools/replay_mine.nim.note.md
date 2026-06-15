# replay_mine.nim — note

**What it does.** The authoritative replay-decode oracle. It loads a recorded
`.bitreplay(.z)` replay, decompresses it (zippy), reconstructs the game by
replaying the recorded inputs through the real sim (`initSimServer` +
`initReplayPlayer` + `stepReplay`), and reports per-slot ground truth as CSV:
`slot,role,reward,tasks,alive,diedTick,dist`. It tracks each player's death tick
and total Manhattan movement distance across ticks. Roles and deaths are
input+seed driven (so they reconstruct exactly); task rewards may diverge
harmlessly.

**Key entry points / usage.**
```
nim c -d:release src/crewrift/replay_mine.nim
./src/crewrift/replay_mine <replay.bitreplay(.z)> [out.csv]   # CSV to stderr, or to out.csv
```
A second argument writes the clean CSV to a file (kept separate from sim stdout
noise); otherwise it goes to stderr. It must be built inside the crewrift repo
(it imports `./replays` and `./sim`).

**Why it matters to the loop.** It is the single source of truth for what actually
happened in a game — the per-slot death/movement/reward oracle that decoding the
S3 replay yields. Server `results.json` and the crewborg trace are matched
observers, but per memory the *authoritative* death/movement oracle is decoding the
replay with this repo binary. Presence-at-kill, isolation, and victim-link
diagnoses all ground out here.

**Status: CURRENT.** The authoritative replay-decode oracle in the working loop;
build it against the live crewrift repo's `replays`/`sim` modules.
