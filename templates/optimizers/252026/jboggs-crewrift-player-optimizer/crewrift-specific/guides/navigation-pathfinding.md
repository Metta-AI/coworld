# Navigation & pathfinding — guide (crewrift tier)

Reference notes, design rationale, and negative results (7).

#### 1. Spend bake budget on pixel-correct reachability and interaction anchors
`crewrift`

Crewrift collides the player as a 1x1 point, so every walkable pixel is a legal position and reachability is one connected component flood-filled from spawn (scipy flood costs ~0.6-1.2s worst case on a fully-open ~813k-pixel mask; run it during camera/stream warmup so it is a one-time startup stall, not per-tick). A coarse (8px) nav graph for A* speed is fine ONLY if correctness stays at pixel resolution: a cell is a node iff it contains a reachable walkable pixel (place the node ON that pixel, not the cell center), join 8-neighbor nodes only when the connecting pixel segment is fully walkable (no diagonal corner squeeze). For each task/vent/button compute a baked anchor = the reachable pixel satisfying the interaction condition (inside task rect / within VentRange of vent center / inside button rect) nearest the natural center, and navigate to that anchor, never the raw rect center.
  <sub>sources: claude-code:962c8ab4-4ea3-4aaa-9f6d-20ea3cfce003, personal_labs/crewrift_lab/crewrift/crewborg/design.md</sub>

#### 2. Hardcode the deterministic Cogs-vs-Clips compound geometry as prior knowledge
`crewrift` · ⚠ _session-derived, unverified_

Bootstrap the fixed crewrift compound layout (a compound.py of fixed hub/station cell coordinates) BEFORE writing localization/map-update code, because dead-reckoning and landmark-matching have nothing to anchor to otherwise. The cogsguard hub/spawn compound is deterministic and symmetric every game (Compound mapgen produces an identical layout from the same CompoundConfig; only randomize_spawn_positions perturbs the spawn pads): the default is a 21x21 inner region with outer_clearance=3 (27x27 footprint), a plus/cross open corridor with four walled corner pockets and four 5-wide 2-deep cardinal gates. Canonical positions: hub center (10,10); spawn pads (10,8) (12,10) (10,12) (8,10); corner extractors carbon (2,2), oxygen (18,2), germanium (2,18), silicon (18,18); gear stations in a row at y=14 centered on x=10. But do NOT hardcode seed-specific clutter: a 'central junction' object existed only in some seeds (seed 7 had the hub at full [48,48] with no object there) -- run a brief game in another seed to confirm a landmark is present in all seeds, and check the hub coordinate separately from any nearby junction. Internalize the coordinate convention: positions are (x,y)=(col,row) but the numpy grid is grid[y,x] row-major, or you silently mirror the map.
  <sub>sources: opencode:ses_1f99651abffeRUPDsPGXgSUaUo, codex:019e0850-2833-7773-a5e4-80ee662745c0, codex:019e28e9-6b45-7c02-b4c7-bb9b0f44e022</sub>

#### 3. Crewrift movement is momentum-based; control with A* plus a release-near-target deadband
`crewrift`

Crewrift movement is momentum-based, not grid-step: input is holding a left/right d-pad direction for a duration (accelerate while held, decelerate after release), so one press != one move. Sim constants (coworld-crewrift/src/crewrift/sim.nim): per-tick Accel=76, MaxSpeed=704, friction 144/256 on the no-input axis, snap-to-zero below StopThreshold=8, sub-pixel MotionScale=256, approx travel ~2.75 px/tick. Walkability is the alpha channel (alpha>0) of the single sprite labeled 'walkability map', sized to the full 1235x659 map -- Snappy-decompress it once and build the nav graph; the only other useful sprite is the dynamic 'shadow' line-of-sight overlay. Navigate with A* (JPS+ or precomputed/baked paths as advanced options) plus a closed-loop controller (PID, or bang-bang with a release-near-target deadband that releases the axis once within estimated stopping distance so the agent coasts onto the target) rather than assuming exact stops. Radar-screen task guesses are fallible (multiple tasks on one line) -- treat them as refinable estimates, not ground truth.
  <sub>sources: coworlds/coworld-crewrift/players/notsus/README.md, coworlds/coworld-crewrift/src/crewrift/sim.nim, personal_labs/crewrift_lab/docs/crewrift-gameplay.md, personal_labs/crewrift_lab/crewrift/crewborg/design.md (+1)</sub>

#### 4. Among Them (Skeld) fixed geometry and walk-mask navigation
`crewrift`

Among Them geometry a parser/bot can hardcode: world 952x534; emergency-button rect {x:524,y:114,w:28,h:34} (home point (536,120)); 40 task stations (16x16 action rects); 15 vents (12x10, grouped A-F, teleporting cyclically through the group); 27 named non-overlapping rooms used only for labeling/chat (never rendered to pixels); off-map pixels render as MapVoidColor (not black); walls are NOT extra-shadowed (it made localization harder). Collision is 1x1 (CollisionW=CollisionH=1) so the static bit-packed walk mask IS the passability grid with no footprint inflation, and the sim slides along walls. A 4-connected A* with Manhattan heuristic over the walk mask suffices (e.g. 443 cells in 6.7ms, ~12% over Manhattan); use a small lookahead (~8) to smooth corners and replan when the player drifts >20 cells or the path exhausts.
  <sub>sources: bitworld/among_them/GRAPHICS_REPORT.md, bitworld/among_them/players/how_to_make_a_bot.md, bitworld/among_them/players/lively_lecun/ROADMAP.md</sub>

#### 5. Among Them has no client wall layer; reactive radar steering traps agents
`crewrift` · **negative result**

Among Them's wall/collision layer lives only on the server and is NOT in the client framebuffer, so per-pixel client wall detection is infeasible. Reactive radar-arrow steering toward tasks therefore walks agents into walls and traps them in the stuck-perturbation cycle (52+ perturbs/30s) so they never reach tasks; reliable task completion requires DELIBERATE navigation (camera localization + persistent map + A*), not purely reactive steering. As a stopgap, detect being pinned by frame-to-frame pixel motion (free movement scrolls thousands of px/frame; stuck differs only by tens due to sprite animation) and after a stuck streak substitute a perpendicular cardinal direction for a few ticks.
  <sub>sources: bitworld/among_them/players/lively_lecun/ROADMAP.md</sub>

#### 6. Naive flee-target projection ignores layout and idles after arrival
`crewrift` · **negative result**

Computing a flee target by projecting the bot through itself away from the threat (fleeTarget = self + 2*(self - body)), clamping to bounds and snapping to the nearest walkable pixel, has a KNOWN WEAKNESS: it ignores map layout, so in a dead-end room the imposter flees toward a wall and wastes time on snapToPassable retargeting before a waypoint route is found -- fleeing toward the nearest room EXIT would be better (snap+waypoint handles most cases, treated low priority). Fleeing mode also doesn't detect arrival, so if it reaches cover before the directive TTL (240 ticks) it keeps emitting movement toward an occupied point and visibly idles; a loiter phase would look more natural. Handle the degenerate self-on-body case (dx==dy==0) with an arbitrary offset so direction stays defined.
  <sub>sources: players_checkouts/players/users/james/personal_cogs/among_them/guided_</sub>

#### 7. When the defended key role and partner are split across rooms, pull the partner to you
`crewrift`

When the defending key role and partner are in different rooms in Crewrift, prefer getting the partner sent to you as a HOSTAGE over moving yourself, and only move into the partner's room if you have VERIFIED intel that the enemy key role is not there -- require the enemy key role's location before deciding to move, because a wrong move risks co-location and loss.
  <sub>sources: agents/eurydice/PERSEPHONE_STRATEGY.md</sub>
