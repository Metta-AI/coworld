# AGENTS.md - CrewRift-Specific Learnings

Do not treat CrewRift runner slots as strategy. Slots can identify connection
URLs, UI widgets, result rows, or exact reproductions. They do not determine
role, identity, route, target priority, social personality, or upload lane.

Check mechanics in source before changing behavior. The important source of
truth is `src/crewrift/sim.nim` in the public/vendored CrewRift source,
especially role assignment, body reports, button calls, voting phases, kill
cooldown, and chat/vote handling.

Optimize shared social competence. Strong CrewRift candidates improve task
credibility, body reporting, observation memory, accusation quality, consensus
handling, vote timing, pressure response, kill conversion, and alibi movement.

Ground meeting behavior in observed facts. Crewmate votes should come from
observed bodies, vents, contradictions, proximity, or strong parsed consensus.
Imposter votes should protect known teammates and pressure legal targets
without inventing body locations.

Movement is continuous control, not grid navigation. Button masks,
acceleration, braking, and overshoot matter; pathing fixes should be justified
by behavior traces, not cleaner-looking routes.
