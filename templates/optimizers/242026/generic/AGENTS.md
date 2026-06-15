# AGENTS.md — generic optimization discipline (always-on)

This is the **generic tier** of a layered knowledge package. It holds principles true for ANY
coding-agent or software-optimization work — measuring a change, reading a noisy signal, debugging a
behavior that does not fire, deciding whether to ship. There is no project, product, or domain in
this tier; it reads coherently on its own. Two outer tiers sit on top of it and apply these
principles to progressively narrower contexts (a domain methodology tier, then a single-project
tier). Those tiers POINT here for the rationale and carry only their own specifics; this tier never
names them or depends on them. If you loaded this as part of a larger package, treat the rules below
as the foundation the more specific guidance refines — never restate them in the outer tiers, just
cite them.

Keep this file loaded every session. It is framing and guardrails — the things that shape *every*
hypothesis. The reference guide `guides/measurement-and-iteration-discipline.md` carries the longer
reasoning; reach for it on demand.

## The iteration loop

All optimization work is the same loop, run honestly:

**orient → form a hypothesis → find the root cause before coding → make the smallest change → measure
→ ship or record the result → loop.**

Two cheap steps prevent most wasted cycles, and both come *before* you write code:

- **Root-cause before implementing.** Read the actual source and the actual signal before coding from
  a hypothesis. Confirm a behavior is even reachable — when something "never happens," audit whether
  its trigger is arithmetically/logically attainable before tuning it. A source-derived claim that
  contradicts observed behavior is wrong; re-trace, don't defend it.
- **Make the minimal change that tests the hypothesis.** One variant = one branch = one commit, so
  each built artifact maps to exactly one diff. When you must compare against a baseline, the baseline
  is the same tree minus only the change — never a stale prior build.

## Measure, don't vibe

No shipping on a hunch. A change is an improvement only when the measurement says so, with the
uncertainty accounted for. The full discipline is in
`guides/measurement-and-iteration-discipline.md`; the always-on core:

- **Compare with confidence intervals, never point estimates.** Overlapping intervals are
  INCONCLUSIVE — never a win. Small samples flip sign; a "win" at tiny n routinely becomes a loss at
  an adequate sample.
- **Extend, don't re-roll.** When a result is directionally interesting but not yet conclusive, add
  more samples to the *identical* setup and pool them. Re-rolling a fresh setup throws away signal and
  invites cherry-picking.
- **Reconstruct before you believe.** A single alarming observation is usually noise. Rebuild it at an
  adequate sample under controlled conditions before treating it as real.
- **A refutation is a result.** Record every measured negative with its numbers so the dead end is
  never rebuilt. A high refutation-to-win ratio is normal and healthy — the negatives are what keep
  the search from looping.

## Wrong action is negative value — gate precision before recall

Doing the wrong thing is worse than doing nothing. Any change whose mechanism is "act more often" or
"consider more candidates" must measure **accuracy alongside volume** before shipping — more volume on
the same evidence is a loss, not a gain. Put the precision gate in *before* you widen recall. See the
guide's "precision before recall" section.

## Descend one causal layer when a fix fails

When an intervention fails to move the metric, do not re-tune the same layer forever. Drop one layer
down the causal stack and measure *there*. Most apparent bottlenecks are downstream of a harder one;
the reusable output of a campaign is often the *ladder of layers you descended*, not any single fix.
See the guide's "descend a causal layer" method.

## Don't copy a behavior expecting its payoff

A capability that works in one system does not carry its payoff into yours. Before porting any
observed-elsewhere technique, classify it: is the benefit **bundled** with a side-effect you can't
take half of? Does it **depend on a capability you lack** (build the prerequisite first)? Are you
copying the **surface action** without the internal state that decides when to take it? A cheap causal
ablation — disable the suspected mechanism and re-measure — often settles in one experiment what weeks
of imitation cannot. See the guide's "classify before porting."

## Fail loud — no silent fallbacks, no result caching

- **Surface errors; never paper over them.** A fallback that silently changes *what gets measured* (or
  *which case runs*) corrupts the result with no error — strictly worse than a loud failure. An
  unexpected rejection is a designed hard stop: surface the validator's message and act on it.
- **Never cache or dedupe measurement results.** The same comparison must be re-runnable many times; a
  cached verdict hides drift. A wedged run fails fast and loud, it does not wait forever or return a
  stale answer.
- **Distinguish infrastructure failure from a real negative result before you act on it.** A crash, a
  timeout, or an environment fault is not evidence about your change. Run a known-good control on the
  same infrastructure to tell "my change is bad" apart from "the harness broke." (see the guide's
  "terminal evidence" section)

## Keep the loop alive and checkpoint state

- **A stalled loop is a silent failure.** If no measurement is in flight and none was started recently,
  the loop is stalled regardless of how healthy things look. Keep work in flight and a heartbeat
  signal up.
- **Background processes die silently across restarts.** Detached pollers and background workers do not
  survive session restarts and often leave an empty log rather than an error. Use a tracked/monitored
  runner, not a fire-and-forget detached process, and checkpoint enough state to a known file that a
  fresh run resumes losslessly. An empty log is not proof of death and not proof of life — check the
  process and its output artifacts.

## Gate outward actions on explicit approval

Anything externally visible or irreversible — publishing, deploying, deleting, filing, sending — is
gated on explicit human approval and done only by the lead actor, never delegated silently to a
sub-process. In-loop iteration that stays local and reversible needs no permission; run it. The line
is reversibility and external visibility, not convenience.

## Working-tree hygiene before you commit or attribute

A dirty working tree silently bundles unrelated work-in-progress into a build, which then confounds
every attribution drawn from it. Inspect the diff before each build and before each commit so you know
exactly what an artifact was built from. When a directive contradicts a recorded lesson, state the
collision and verify empirically before *and* after — and be ready for the lesson to win.
