# MANIFEST — coworld-player optimization methodology (tier 2)

The middle tier of the three-tier package. It carries the methodology that transfers to optimizing
ANY scripted or LLM-driven player for ANY Softmax **coworld** league — a hosted, adversarial,
mixed-role matchmaker where you ship a container into a seat and read scores back. It **applies** the
generic tier (`../generic`, pure measurement/iteration discipline) and is in turn **specialized** by a
project tier that carries one specific game's numbers, IDs, source-line cites, and commands.

This tier names no specific game: no notsus, no sim.nim, no league/division IDs, no tier names, no
measured numbers, no literal N-floor — only the transferable *shape* (verified by scan). The generic
principles it leans on are stated only in the generic tier and referenced, not restated.

One row per file. **"Generalizes from"** names the universal-package material each file abstracts (the
source of truth is `../universal`).

| Item | type | What it is | Generalizes from (universal sources) |
| --- | --- | --- | --- |
| `AGENTS.md` | always-on | The keep-loaded coworld-player guardrails: the eval surface is a real hosted league (competitor images are private → measure server-side, never local self-play); pin the four scoring facts from the game's own source (seat/role distribution, exact win/terminal condition, what-the-lever-depends-on, leaderboard aggregation = lagging lifetime mean → durable rank is time-gated); leaderboard-slot ("champion") is a label not a quality signal; measurement is generic-apply-don't-restate, but calibrate the instrument against the live field; the two-slot live A/B + totality-of-evidence promotion (windowed gate can never fire; live-mix replica arms are the binding gate); re-resolve live state every launch; fail-loud on forced-seat rejection + no result caching; keep-loop-alive + gate league-visible actions; verify-before-porting (read-your-own-bot, fire-rate, the cheap config-ablation — taxonomy itself lives in the generic tier). | `universal/AGENTS.md` §"scoring & win model", §"champion is a slot label", §"two-slot live A/B and promotion", §"re-resolve live state", §"fail loud", §"keep the loop alive", §"verify before porting" — generalized: every crewrift number/ID/source-cite replaced by "the project tier states the actual …". The server-side-not-local premise is lifted from `universal/guides/experience-request-and-league-api-reference.md` + the league-eval design intent. |
| `guides/coworld-league-eval-methodology.md` | guide | The game-agnostic eval methodology: why the eval is server-side and what that forces; the paired forced-role A/B and its honesty invariants (force-role-or-fail-loud, pin-the-seed + spread-across-seeds, verify-who-landed-where, run-arms-concurrently, scale-poll-timeout); finding/confirming a crux (standings deltas, round reconstruction, swap tournaments, the counterfactual swap, rival mining, user observation); ground-truth escalation (per-agent logs → replay oracle → rival telemetry → config-ablation); the composed promotion gates; re-resolve-the-roster-every-launch; the once-per-roll version-roll migration. Shapes and traps only — no commands. | `universal/guides/experience-request-and-league-api-reference.md` (server-side eval, roster resolution, timeouts) + `universal/guides/crux-loop-and-asana-state.md` (crux/swap/promotion mechanics) + `universal/guides/coworld-version-roll-migration.md` (the migration procedure) + the eval-design substance in `universal/skills/run-league-ab-eval`, `generate-a-crux`, `resolve-live-roster-and-champion-state`, `decode-replay-ground-truth` — all stripped to game-agnostic shape; concrete endpoints/IDs/decode-tool deferred to the project tier. |
| `guides/coworld-optimization-loop.md` | guide | The end-to-end loop as a command-free **shape**: the 8-stage cycle (orient → pick lever → root-cause → edit the bot → build+upload → server-side paired A/B + decode ground truth → ship/refute → record), the standing ground rules, and the failure-handling sub-loops (wedged match, server API drift, backend-outage triage, background-process death, bot-plays-dead, local-smoke false alarms). It is the spine that orders the methodology guide and the generic discipline. | `universal/LOOP.md` (the concrete crewrift loop) abstracted of every command and source path + `universal/guides/crux-loop-and-asana-state.md` (the resumable 4-stage backbone). |
| `guides/cross-coworld-craft.md` | guide | The standing cross-league craft that holds across worlds, extracted from a sibling coworld: match the wire-protocol FAMILY not the commissioner key; gate a candidate across the FULL role/slot matrix not just the targeted slot; wait for terminal completed evidence (no single-round whiplash / partial-active reads); record every failed candidate as a NAMED no-upload negative control; run two owned identities as swappable blue/green lanes (don't churn-rename). | `universal/guides/cross-coworld-craft.md` — already game-agnostic in the universal package; this copy additionally strips the two "Crewrift-specific tie-in" blocks (the N≥30 bar and the Asana tracker pointer) down to project-tier pointers, and genericizes the "co-gas" sibling-world name. |

## Orthogonality & standalone contract

- The pure statistics (CI verdicts, minimum-n, pooling, extend-don't-re-roll) and the bare fail-loud /
  root-cause / refutations-are-results / classify-before-porting *principles* are stated **only** in
  the generic tier; this tier names the coworld-specific shape and points there.
- This tier reads coherently **without** the project tier: every project-specific value is replaced by
  an explicit "the project tier states the actual …" pointer, never an assumption that tier 1 is
  loaded. No crewrift noun and no tier-1 filename appears here (verified by scan).

## Who loads this tier

- A crewrift agent loads all three tiers.
- An agent optimizing a player for a **different** Softmax coworld loads this tier + the generic tier
  (and writes its own project tier).
- A generic optimization task loads the generic tier alone and does **not** load this tier.
