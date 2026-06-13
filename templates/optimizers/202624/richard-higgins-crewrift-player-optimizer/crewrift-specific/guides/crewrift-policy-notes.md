# CrewRift Policy Notes

The strongest shared lesson is that CrewRift is a social behavior game with a
protocol surface, not a slot-routing puzzle.

Useful failure classes:

- vote cursor or deadline timeout;
- skipped body-report evidence;
- illegal teammate vote;
- weak or invented accusation;
- role-inference error;
- imposter zero-kill or stale prowl;
- cooldown chasing before kill readiness;
- fake-task or alibi movement that looks suspicious;
- body report timing;
- task-complete crew loss despite poor social outcome;
- partial artifact fetch hiding the true batch.

The v108 Suspectra lesson is narrow: remembering a visible target during kill
cooldown can be useful, but hard-chasing before the kill icon is ready can make
the imposter obvious. Prowl until kill readiness, then hunt.

The RelhAlpha crewborg lesson is operational: record the active starter policy,
build a live roster, fetch all artifacts, and verify player identity before
submission. A good policy can still land in the wrong lane if the identity flow
is wrong.

Route failures to the specific parser, controller, planner, or strategy surface
instead of patching symptoms in the outer loop.
