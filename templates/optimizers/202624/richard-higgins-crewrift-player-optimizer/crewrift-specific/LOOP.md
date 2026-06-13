# CrewRift-Specific Loop

1. Identify the policy family and lane, such as `suspectra`, `crewborg`, or
   another source-backed CrewRift player.
2. Read the CrewRift guide and source owner map for that policy.
3. Build a current roster from live league data before requesting experience.
4. Fetch completed artifacts explicitly; do not rely on downloader defaults.
5. Classify low rows by behavior: vote timeout, skipped body evidence,
   illegal teammate vote, stale prowl, imposter zero-kill, task-complete crew
   loss, role-state bug, provider error, or movement/pathing failure.
6. Check `sim.nim` for the relevant mechanic.
7. Patch the owning parser, planner, controller, or strategy function.
8. Re-run a targeted local/replay diagnostic, then request hosted comparison.
9. Promote only from completed hosted evidence.
