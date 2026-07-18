# Meetings, voting & social deduction — guide (generic tier)

Reference notes, design rationale, and negative results (1).

#### 1. Budget two-party handshake timeouts and fix give-up rationale even when timing is right
`generic` · **negative result** · ⚠ _session-derived, unverified_

NEGATIVE RESULT: default timeouts tuned for solo behavior are too tight for a cooperative two-party handshake -- budget the full round trip, not a one-sided wait (e.g. a key-exchange timed out at 96 ticks and the offer window at 72 ticks, so an agent issued an offer then exited before a partner could respond; the fix doubled them). A terminal give-up condition can be right about WHEN but wrong about WHY: a give-up trigger had correct timing but a false stated prerequisite -- fix the rationale even when timing is sound, because maintainers and future agents reason from it. And distinguish 'impossible' from 'low-probability': a hard gate that treats a still-possible-but-unlikely outcome as impossible prematurely abandons better moves, so model it probabilistically with the give-up path as a SECONDARY fallback.
  <sub>sources: claude-code:aae25940-ade3-41bc-b817-517dc86ccebf, opencode:ses_1fb148d00ffe5ob6k0yKT3aHke</sub>
