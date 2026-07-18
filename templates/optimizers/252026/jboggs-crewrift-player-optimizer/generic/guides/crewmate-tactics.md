# Crewmate tactics — guide (generic tier)

Reference notes, design rationale, and negative results (5).

#### 1. Test a correlation against its competing explanation before designing for it
`generic` · **negative result** · _see related: U0221 (other tier)_

Before you build a fix or feature on top of an observed correlation, name the competing explanation and test it. An apparent A->B relationship is often A and B both driven by a confounder C; if you design for the A->B story you optimize the wrong lever. Concretely, classify an apparent 'surplus' or 'waste' by its generating mechanism (genuine over-supply vs loss/leakage downstream) before reallocating resources, because the two demand opposite remedies and the wrong one compounds the problem.
  <sub>sources: opencode:ses_1fb299595ffeQdQJTUCJtJD6Yu, opencode:ses_1ff2ef8c8ffej7zC4A18jgSDFv</sub>

#### 2. Order mode-selector branches: capability/state gates before tactical branches
`generic` · **negative result** · ⚠ _session-derived, unverified_ · _see related: U0230 (other tier)_

In a mode/state-selector for any agent, evaluate capability and lifecycle-state gates (e.g. dead/disabled -> terminal mode, missing-precondition -> safe default) BEFORE situational tactical branches. Otherwise an agent can enter logic it has no capability to satisfy and thrash on it indefinitely -- fixating on an action it can never complete and cycling between sub-behaviors, wasting compute and self-defeating. Make 'can I actually perform this?' a guard in front of 'should I perform this?'.
  <sub>sources: claude-code:4430a077-5411-426b-a87a-75512ec4300f, claude-code:91f456a7-41e8-4a89-98e9-44e379160b15, codex:019e7174-3079-7351-b8ea-b1bfcb917ff4, codex:019ea961-a6a9-7f42-ba2e-c8b65df11c22</sub>

#### 3. Any action gated on external state needs a retry budget; gate evidence-free fallbacks
`generic` · **negative result** · ⚠ _session-derived, unverified_ · _see related: U0232 (other tier)_

An action whose completion depends on an external state change you do not control can fail to ever complete; without a per-target attempt counter, backoff, or blacklist the agent re-selects the same target and loops forever (one observed loop lost ~65% of a run). Always bound such actions and abandon a never-satisfiable target. Separately, gate evidence-free 'nearest/cheapest' fallback heuristics behind a warm-up or a weak-evidence requirement so they cannot commit on the very first frame before any real evidence has accumulated.
  <sub>sources: opencode:ses_1ff325156ffei2UiDygaVOZo5O, opencode:ses_21a4f6bb3ffepgWI170Xv63XFW, codex:019e196e-93c2-7523-8da7-96f782ea578c</sub>

#### 4. One defect of a class is signal to audit every sibling for the same defect
`generic` · ⚠ _session-derived, unverified_ · _see related: U0243 (other tier)_

When you find one instance of a defect class -- a half-finished mode, a stale comment, a no-op stub reachable only by an obscure path -- treat it as strong evidence the same defect exists elsewhere and audit every sibling (every other mode/branch/handler) for it rather than fixing the one you tripped over. Relatedly, when modelling a required behavior set, derive it by walking each real usage scenario end to end ('what must this actor do at each phase?') instead of brainstorming a flat list of verbs, which misses phase-specific cases. Take inspiration from an existing janky implementation but rewrite it; code already flagged janky is unfit to copy verbatim into a new path.
  <sub>sources: opencode:ses_209613a85ffeqO1Gq9NEDobBYi, opencode:ses_21a4f6bb3ffepgWI170Xv63XFW, opencode:ses_21e58aef7ffeoJ7uZeDgGBCfIh</sub>

#### 5. Don't let a severity gate starve the mechanism it feeds
`generic` · **negative result** · ⚠ _session-derived, unverified_

A gate (severity threshold, filter, guard condition) sits upstream of a mechanism that fires on the events the gate lets through. Tightening the gate can starve the mechanism so it never fires, and because the mechanism then simply does nothing the failure is silent -- no error, just lost benefit. Tune such gates against the DOWNSTREAM event volume they produce, not in isolation: confirm enough events survive the gate to drive the mechanism. (Example: a vibe-driven role-rebalancer needed severity_threshold=1 / min_observations=2 to fire enough; a flat threshold=2 or a unanimity guard suppressed too many events and killed the benefit.)
  <sub>sources: opencode:ses_2042c1ff1ffefETImBU5n4D43k</sub>
