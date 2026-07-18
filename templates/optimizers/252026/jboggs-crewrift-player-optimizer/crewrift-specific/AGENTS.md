# AGENTS.md — always-on heuristics (Crewrift-specific learnings)

Heuristics that are only true or only actionable with crewrift / crewborg / Among-Us-style social-deduction specifics: roles, suspicion modeling, meetings & voting, kills/vents/positioning, the crewrift sprite-v1 protocol, and the related deduction games (persephone, among_them). For the optimization machinery that is NOT crewrift-specific, see the **loop** package; for game-agnostic software/agent lessons, see the **generic** package.

_Load every session. 3 always-on heuristics. ⚠ marks session-derived, unverified items._

## A/B methodology & attribution

#### 1. Never judge Crewrift on a merged crew+imposter win rate; decompose by role
`crewrift`

Crewmate and imposter are effectively two different policies with different objectives, action sets (kill/vent exist only for imposters), and score structures, so a merged win rate routinely hides one role being completely broken. Always decompose evaluation by role (the single most important cut), target experience requests at matched roles for role-specific changes, and run a regression scan to catch fixing one role at the cost of the other.
  <sub>sources: claude-code:784eb0e8-27ad-45ec-9479-9ffadd0d0d28, claude-code:3c867a71-3057-4e87-a149-4185e82ee728, personal_labs/crewrift_lab/best_practices.md, personal_labs/crewrift_lab/docs/crewrift-gameplay.md (+2)</sub>

## Meetings, voting & social deduction

#### 2. Stay connected and always cast at least a skip vote
`crewrift`

Crewrift scoring punishes flakiness and abstention hardest: a disconnect/connection timeout costs -100 (the largest swing in the table) and failing to vote before the timer costs VoteTimeoutPenalty=-10, while an explicit skip (vote code -2) is a free valid vote with no penalty. Design players to stay connected, exit cleanly with status 0 when the socket closes, and ALWAYS cast at least an explicit skip every meeting -- a flaky player that crashes mid-game is worse than a weak one.
  <sub>sources: personal_labs/crewrift_lab/docs/crewrift-gameplay.md, personal_labs/crewrift_lab/docs/crewrift-player.md, coworlds/coworld-crewrift/src/crewrift/sim.nim</sub>

## Crewmate tactics

#### 3. Crewrift core rules, scoring, and the parity-vs-task race
`crewrift`

Crewrift is a Coworld Among-Us-style social-deduction game. Crew win by completing all assigned tasks OR voting out all imposters; imposters win at parity (alive-imposters >= alive-crewmates), so design imposter play around reaching parity, not eliminating everyone. A task completes only by standing motionless in the assigned, incomplete task rect while holding A for TaskCompleteTicks=72 (~3s); any directional input cancels and resets progress, so a task policy must suppress all movement during the hold. One physical rect can be assigned to multiple players with per-player flags, and because imposters cannot complete tasks the global task counter is a lie detector (appears to task but counter doesn't advance = faked). Scoring: win +100, task +1, kill a crewmate +10, vote timeout (no vote or skip cast) -10, StuckPenalty -1 once per StuckPenaltyTicks=480 (~20s) for a crewmate with unfinished tasks that is neither tasking nor moving -- so always cast some vote and keep crewmates moving or tasking. Crew wins are a parity-vs-task race: dead crewmates become ghosts that keep completing their OWN assigned tasks (applyGhostMovement runs; replay emits 'completed task N while dead'), so finishing all 8 tasks is a primary win path and a killed crewmate's task contribution is never zero; the imposters' only resource is the parity clock (remove ~4 crew before the ~48 remaining tasks complete).
  <sub>sources: bitworld/among_them/bot-policies/sidecar/prompts/system.md, bitworld/among_them/bot-policies/sidecar/prompts/crewmate.md, coworlds/coworld-crewrift/README.md, bitworld/among_them/players/lively_lecun/ROADMAP.md (+11)</sub>
