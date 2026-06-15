# MANIFEST — generic optimization discipline (tier 3)

The innermost tier of the three-tier player-optimization package. It holds principles true for ANY
coding-agent or software-optimization work — there is no game, league, or project in it. It reads
coherently alone, and the two outer tiers (coworld-player methodology, then the crewrift project)
POINT here for the rationale instead of restating it.

One row per file. **"Generalizes from"** names the universal-package material each file distills (the
source of truth is `../universal`); the universal package mixed these principles together with
crewrift specifics — this tier is the specifics-stripped residue.

| Item | type | What it is | Generalizes from (universal sources) |
| --- | --- | --- | --- |
| `AGENTS.md` | always-on | The keep-loaded generic guardrails that shape every hypothesis: the iteration loop (orient → hypothesis → root-cause → minimal change → measure → ship/record); measure-don't-vibe (CI verdicts not point estimates, extend-don't-re-roll, reconstruct-before-belief, refutations-are-results); wrong-action-is-negative-value / precision-before-recall; descend-one-causal-layer; don't-copy-a-behavior-expecting-its-payoff (the bundled / depends-on-capability / surface-vs-mechanism taxonomy + cheap ablation); fail-loud / no-silent-fallbacks / no-result-caching / infra-vs-real-negative; keep-the-loop-alive + checkpoint-state; gate-outward-actions-on-approval; working-tree hygiene before build/commit. | `universal/AGENTS.md` §"Measurement discipline", §"Fail loud", §"Keep the loop alive and league actions gated", §"Verify before porting" — with all crewrift bindings (Wilson-by-name, N≥30, parity, notsus, league IDs) removed. Also the always-on core of `universal/guides/refuted-levers-do-not-rebuild.md`'s descend-a-layer method and `universal/LOOP.md`'s orient→…→record spine, abstracted of commands. |
| `guides/measurement-and-iteration-discipline.md` | guide | The long-form reference behind the AGENTS.md core: ten composable sections (measure-don't-vibe; CI-verdicts-not-points; extend-don't-re-roll + pool-same-direction; reconstruct-before-belief; refutations-are-results; the descend-a-causal-layer debugging method; precision-before-recall; classify-before-porting + cheap ablation; named negative controls; terminal-evidence + infra-vs-result), plus a "how these compose" synthesis. No domain in any section. | `universal/AGENTS.md` measurement/porting/fail-loud sections at full depth, plus the transferable method-shape of `universal/guides/cross-coworld-craft.md` §3–4 (terminal evidence, named negative controls) and `universal/guides/refuted-levers-do-not-rebuild.md` (descend-a-layer, refutation-as-result) — every league/game noun stripped. |

## Orthogonality contract

- This tier states each principle **once** and is the canonical home for it. The coworld-player and
  crewrift tiers must name a principle and point here, never re-spell its definition.
- This tier mentions **no** game, league, bot, vendor, or project noun (verified by scan). If a
  sentence here only makes sense with a specific game in mind, it belongs one tier out, not here.
- "Wilson" appears once in the guide as the standard interval choice for a proportion — a generic
  statistics fact, not a project binding. The literal sample-size bar (N≥30) is deliberately NOT here;
  it lives in the crewrift tier as that league's instantiation of the abstract minimum-n floor.

## Who loads this tier

- A crewrift agent loads all three tiers (this + coworld-player + crewrift-specific).
- An agent optimizing a player for a **different** Softmax coworld loads this + the coworld-player tier.
- A generic coding-agent / optimization task loads **this tier alone**.
