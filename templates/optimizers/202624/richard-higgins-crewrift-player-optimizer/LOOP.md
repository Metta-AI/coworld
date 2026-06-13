# LOOP.md - Integrated CrewRift Player Optimization Loop

This loop integrates the co-gas remote-XP work and the RelhAlpha/player-labs
onboarding loop from the machines that had direct CrewRift optimizer findings.
Titan was reviewed, but it did not add direct CrewRift loop evidence.

1. Refresh the repo and read the local agent guide.

   Start from the active repo's `AGENTS.md` plus the relevant player or lab
   guide. For co-gas, use `reports/latest.md`, `docs/coworld-tournament-playbook.md`,
   and the candidate YAMLs. For player-labs, read the lab guide, best practices,
   and any recorded user preferences.

2. Confirm identity, lane, and baseline.

   Decide whether the work is for Richard Higgins or RelhAlpha. Record the
   selected policy family (`suspectra`, `crewborg`, or another source-backed
   CrewRift line) before editing so future sessions do not switch lanes
   accidentally.
   Verify the current active membership or baseline policy version from live
   data, not memory.

3. Build the current evaluation roster from live state.

   Query the current CrewRift league, division, leaderboard, memberships, and
   active policy versions before creating hosted experience. Fill the intended
   seat count with opponents that are actually active in the target league or
   division. Do not reuse stale rosters from older sessions.

4. Generate or fetch experience before editing.

   Prefer completed hosted XP or completed live artifacts when they exist. Use
   short local episodes when they are the fastest way to reproduce or instrument
   a concrete behavior. If using a hosted experience request, validate the body
   locally first, post it, poll until terminal, and fetch the full completed
   artifact count explicitly.

5. Inspect artifacts until one failure is operationally named.

   Good failure names are behavior-specific: vote cursor timeout, skipped body
   evidence, illegal teammate vote, stale prowl, imposter zero-kill case,
   provider error, role-inference bug, task-complete crew social loss, movement
   overshoot, or ungrounded accusation. If the cause is vague, inspect more
   replay/log detail or add focused instrumentation.

6. Check CrewRift mechanics from source.

   For mechanics claims, read `cogas-agents/coworlds/crewrift/vendor/coworld-crewrift/src/crewrift/sim.nim`
   or the current public CrewRift source. In particular, slots are runner
   metadata unless a fixture explicitly fixes slot roles.

7. Patch the smallest owner.

   Route the failure to its owner: protocol parser, role detector, vote parser,
   meeting chat grounding, map/task targeter, path follower, body reporter,
   imposter kill timing, fake-task/alibi behavior, candidate ledger, or upload
   identity flow. Make one behavior change whose evidence can accept or reject
   it.

8. Add the narrowest regression or guard.

   Use parser fixtures, replay assertions, source assertions, deterministic
   scenarios, or focused local episodes. Large scripted policies may need source
   tests that assert both the desired behavior and the absence of rejected paths.

9. Run focused local checks.

   Run the policy's tests, source validation, candidate validation, schema
   checks, and short local diagnostics that cover the changed behavior. Local
   success means "ready for hosted comparison", not "ready to promote".

10. Record candidate evidence.

    Update the durable ledger (`experiments/candidates/*.yaml`, lab
    `version_log.md`, or the package's performance log) with the observed
    failure, source correction, artifact paths, policy/image/version IDs,
    metrics, and current decision.

11. Upload without changing tournament membership.

    For co-gas, use `submit-source --no-submit` on the lower owned lane. For
    player-labs or direct Coworld flows, verify that the new policy version is
    created under the intended player identity before submitting it anywhere.

12. Request hosted comparison evidence.

    Request XP against current public leaders, the lower owned champion, and
    recent bad matchups. Use seat rotation where available so slot position is
    measured as metadata, not strategy. Poll to completion and fetch the full
    artifact set.

13. Decide from completed artifacts.

    Promote or submit only when completed hosted evidence and inspected
    artifacts show the candidate is meaningfully better for the target lane. If
    the result is negative or incomplete, record a hold, preserve the lesson,
    and start the next iteration from the low artifacts.
