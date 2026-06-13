# Performance Log

## 2026-06-13 - Integrated extraction across four machine runs

The four extraction runs describe two concrete CrewRift policy trajectories.
Titan was reviewed, but it did not contain direct CrewRift optimizer evidence.

The co-gas Richard/Suspectra trajectory moved from source-custody repair and
local diagnostics into a hosted XP gate. The strongest completed evidence in
the extracted corpus is `crewrift-suspectra-richard:v98`: a top-field XP
request completed 72/72 episodes, removed the vote-timeout floor seen in v97
low artifacts, averaged about 41.14, ranked third in that XP set, and was
submitted as Richard's live champion. Later no-submit variants v99-v107 tested
plausible changes, but artifact review rejected the weaker vote-pileon and
protocol experiment paths. v108 was built and uploaded no-submit with a narrow
imposter cooldown change, but no completed v108 XP request existed at
extraction time, so v108 is not promotion evidence.

The RelhAlpha/player-labs `crewborg` trajectory started from a fresh
RelhAlpha-owned baseline. The first hosted evaluation completed 32/32 episodes,
but the initial artifact fetch only downloaded 10 until rerun with an explicit
count. The session recorded `RelhAlpha:v1` as baseline, `RelhAlpha:v2` as the
first modified upload, and `RelhAlpha:v4` as the version actually assigned to
RelhAlpha and submitted after fixing the player-identity flow. A provisional
leaderboard snapshot at the end of that session showed RelhAlpha rank 1 with
score about 75.84 and Richard rank 4 with score about 72.42 while the round was
still running, so treat that as session evidence, not a stable final result.

The Titan extraction did not find a direct CrewRift score trajectory in local
sessions. Its unrelated replay-debugging material was cut from active guidance;
the gap is recorded rather than converted into invented CrewRift findings.

Next optimizer work should append new entries after completed hosted evidence:
policy version, opponent roster, episode count, score distribution, low-artifact
failure classes, exact source changes, and the promote/hold decision.
