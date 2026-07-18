# Perception & state decoding — guide (generic tier)

Reference notes, design rationale, and negative results (10).

#### 1. Pick the FFI boundary by measurement; cut at the outermost hot loop and parity-test native kernels
`generic` · ⚠ _session-derived, unverified_

Choose language/FFI by MEASUREMENT, not reflex: a 128x128 4-bit frame parses in NumPy in <5ms, so Python with NO C/Rust FFI was correct (preserve multi-language access via a CLI mode, stdin bytes -> stdout JSON, not FFI). When going native, rank hot spots by ops-per-call (sprite-anchor matching at ~60-100 numpy passes/call dominated; a central-sounding ~24us camera-scoring call was trivial) and cut at the OUTERMOST hot loop: moving the single 24us kernel to ctypes gained nothing (marshalling fully erased it), but moving the entire voting/localization loop that called it ~289x/frame into ONE native call dropped the cold path 5.6x (4.69ms -> 0.84ms). Gate the native path behind a load flag plus a disable env var and give every native kernel a PARITY test vs the numpy baseline, comparing what the CALLER consumes (a native early-exit kernel diverged in raw error counts but made the identical accept/reject decision), and NEVER overload a valid result as a give-up sentinel (returning 0 for 'budget exhausted' was indistinguishable from 0 = perfect match; use best_errors+1).
  <sub>sources: opencode:ses_20c066070ffeBjXMnfQULai0Lw, opencode:ses_21e7f66a8ffeNFrL2URK8EWAn7</sub>

#### 2. Treat 'action sent' as a request, not a result; confirm effects through observation
`generic` · **negative result** · ⚠ _session-derived, unverified_ · _see related: U0727 (other tier)_

An action handler can only report that it SENT a command, never that the command succeeded - the effect may be blocked, dropped, or silently fail downstream. Treat an action as 'taken' only once you observe the resulting state change, not when the call returns. If you have no way to detect an action's effect, that is an observability gap to close, not a reason to assume success. Confirm a specific outcome by the specific artifact it should produce near a known anchor, never by a global aggregate that can move for unrelated reasons. And watch for environment bugs that silently break the send-then-confirm contract (a returned call can still have had zero effect).
  <sub>sources: players_checkouts/players/docs/findings/baseline-policy-recipe-discove, players_checkouts/players/players/cogsguard/role/CLAUDE.md, players_checkouts/players/players/cogsguard/role/aligned_junction_held, opencode:ses_209613a85ffeqO1Gq9NEDobBYi (+1)</sub>

#### 3. Shared code shares blind spots; reuse propagates latent bugs that tests over the common path never catch
`generic` · **negative result** · ⚠ _session-derived, unverified_ · _see related: U0731 (other tier)_

Two independently-written components that share the same underlying algorithm share the same BLIND SPOTS: if both use an identical gate or parser, both fail on the same rare input, and a passing test suite that never exercises that rare state proves nothing. Treat code reuse as also propagating latent bugs, not just behavior - when you adopt a shared implementation, you inherit its untested failure modes, so test the rare/edge states explicitly rather than trusting that 'it works in the other component'.
  <sub>sources: opencode:ses_1fb148d00ffe5ob6k0yKT3aHke, opencode:ses_20101b42dffeJU331wyDQFEn9W</sub>

#### 4. Verify field schemas against the producing code, not the brief; parse drifting layouts defensively
`generic` · **negative result** · ⚠ _session-derived, unverified_ · _see related: U0732 (other tier)_

Before writing code against a data structure, verify its field schema against the live code that PRODUCES the field, not the task prompt or brief: grep the actual struct to confirm every field exists and has the layout you assume. Briefs are routinely wrong (a brief promised memory.players[color].lastSeenRoom but the code only stored last-seen coordinates; a spec described a tuple as (tick,x,y) but the updater wrote (x,y,tick)), and getting the layout wrong silently corrupts every derived value because the wrong values still typecheck. Treat any field named in a prompt as a claim to confirm, not a given. When a field's layout is ambiguous or drifts between contexts (synthetic fixtures vs live data), parse it defensively to accept both forms from one code path so tests and production both stay correct.
  <sub>sources: codex:019e05e2-eadc-70a1-a58f-add2c62f1046, codex:019e08bb-a4ea-7c83-a8d6-2652eaa1a3b8, opencode:ses_1ffc701efffeS5c5ueXd2vWIkD</sub>

#### 5. Make reset() clear ad-hoc attributes too, or keep persistent state in a declared container
`generic` · ⚠ _session-derived, unverified_ · _see related: U0740 (other tier)_

When a state/world-model object permits ad-hoc attributes (setting obj.foo outside the declared schema), reset() must clear them too: after re-defaulting the declared fields, iterate self.__dict__ and delattr any name not in the declared field set, or stale state silently survives a restart. The cleaner rule is that any state which must persist belongs in an explicit declared container, not an ad-hoc attribute, so reset semantics are unambiguous.
  <sub>sources: claude-code:4430a077-5411-426b-a87a-75512ec4300f, claude-code:48add98e-a83d-4348-97bf-0079c48c42d6, codex:019e03bf-982c-7fc0-8ba9-d4c640feb779, codex:019e04e9-c357-7c71-a255-929f3a97fda1 (+3)</sub>

#### 6. Before deduplicating perception constants, confirm intent and recompute the metric by hand
`generic` · ⚠ _session-derived, unverified_

Before collapsing two near-identical constants, confirm INTENT: they may be intentionally different by one unit (e.g. a mask-alignment center vs a world-offset geometry center differing by one pixel); if both must stay, rename them to encode their distinct purpose. When a dedup or metric test fails, recompute the metric BY HAND before changing code - a Chebyshev-distance dedup that 'wrongly' kept two points was correct and the test's expected count was wrong, not the code. When merging two branches, decide PER-FEATURE which side to keep (take one branch's cleaner refactor but keep the other's richer data path), because a refactor that FLATTENS a structured field silently fails to typecheck against consumers expecting the structured form.
  <sub>sources: opencode:ses_21b7f7f7cffeDDc56Goq1NPBmv, opencode:ses_21bd5a030fferp2y09ldDj5jjw, opencode:ses_21ece5489ffeFZNEP6Ehx80GI1</sub>

#### 7. Treat unvalidated perception thresholds and untested code orderings as suspect, not tuned
`generic`

Distinguish empirically-validated parameters from initial guesses, and make the guesses your first suspects when quality regresses - a threshold or code ordering that was never validated is suspect, not tuned. (Example: a teleport-detection pixel threshold was never validated and may still hold its initial guess, and the ordering of 'score against last frame' vs 're-localize then re-scan' after a teleport was never resolved because parity was declared sufficient on a sample that lacked teleport-heavy cases; if quality regresses post-teleport, suspect both first.)
  <sub>sources: bitworld/among_them/players/mod_talks/TODO.md</sub>

#### 8. Code placed in a branch that never runs is dead; verify which branch actually executes
`generic` · **negative result** · _see related: U0758 (other tier)_

A side effect (e.g. appending a record) placed in one branch of a conditional can be silently dead code when an earlier guard or state-clearing step in the sibling branch fires first under the real input, so the intended branch is never reached. Verify which branch actually executes for the triggering case rather than assuming, and when a finalize step must run regardless of branch, extract it and invoke it from the branch that genuinely runs (or unconditionally) instead of nesting it where it can be bypassed.
  <sub>sources: bitworld/among_them/players/mod_talks/LLM_SPRINTS.md</sub>

#### 9. Verify a feature is actually emitted by the implementation, not merely registered or enabled
`generic` · **negative result** · _see related: U0762 (other tier)_

Do not assume a capability/feature is available because it is registered in a config or registry - VERIFY it is actually produced by the implementation that emits it (e.g. the compiled engine), not the higher-level layer that only declares id/name/metadata. A registry declares intent; the producer decides reality, and the two routinely diverge (features can be enabled in config yet never referenced in any emission path - dead). Trace from the registry definition to the config flag that enables it, then confirm empirically (e.g. a token/output dump) that the value actually appears before building logic on it.
  <sub>sources: archive/cogames_playground/bulbacog/COGS_V_CLIPS.md, alpha_cog/AGENTS.md, opencode:ses_1f98db060ffeKMm2h0af93sMl4, opencode:ses_200493314ffeuU44LQ1zuZaduk (+3)</sub>

#### 10. Keep an agent's own id in its peer set so empty-observation fallback degrades safely
`generic` · _see related: U0767 (other tier)_

In multi-agent coordination that assigns roles by comparing observed peer ids, keep an agent's own id in its own observed-teammate set. Then an agent that has seen no other teammates by the assignment deadline still has a non-empty set and falls back safely (e.g. assumes it is the highest-id visible and takes the lead role) instead of crashing or deadlocking on an empty set.
  <sub>sources: archive/cogames_playground/bulbacog/designs/MEMORY.md, archive/cogames_playground/bulbacog/designs/STRATEGY_V2.md</sub>
