# Optimizer Learning Package — METADATA

| field | value |
|---|---|
| **topic** | Optimizing a scripted/LLM player (the `notsus` bot) for the **crewrift** Coworld league |
| **author handle** | daveey |
| **author contact** | daveey@gmail.com (Softmax) |
| **coworld** | crewrift (Crewrift Daily league); bot repo `Metta-AI/coworld-crewrift`, harness repo `daveey/crewrift` |
| **extracted** | 2026-06-14 (ISO week 24 / 2026) |
| **optimization period covered** | 2026-06-05 → 2026-06-12 |
| **tiers** | 3 — `crewrift-specific` (project) ⊃ `coworld-player-generic` (domain) ⊃ `generic` |
| **search roots swept** | `~/code/crewrift` (+ nested `_crewrift-*` bot checkouts); `~/.claude/projects/-Users-daveey-code-crewrift/memory/` (26 notes); coding-agent transcripts under `~/.claude/projects/*` and `~/.codex/sessions/*` (27 on-topic, 21 mined) |
| **extraction tool** | `Metta-AI/metta` skill `extract-learning-package` (docs/ai/onboarding/workflows) |

## What this is

A portable, layered knowledge base a fresh coding agent can mount to resume — or transfer —
player-optimization work. Built by mining this machine: first the session transcripts (the
unwritten lessons + the reconstructed working loop), then the on-disk corpus (agent docs, memory
notes, skills, bot source, harness tools), consolidated into one `universal/` package and then split
by subtraction into three orthogonal tiers.

## Layout

- `METADATA.md` — this file.
- `TIERS.md` — the partition map: what each tier is for and which agent loads which combination.
- `LOOP.md`, `performance/LOG.md` — top-level convenience copies (canonical copies live in
  `universal/` and `crewrift-specific/`).
- `universal/` — the undivided package (source of truth for re-runs): `AGENTS.md`, `LOOP.md`,
  `MANIFEST.md`, `skills/`, `guides/`, `tools/`, `performance/`.
- `crewrift-specific/` — tier 1: the irreducible crewrift residue (refuted-levers ledger, notsus
  architecture, 8 skills, 15 harness tools, performance log, subtracted always-on `AGENTS.md`).
- `coworld-player-generic/` — tier 2: the coworld-league optimization methodology (server-side
  forced-role A/B, crux loop, promotion gates, roster resolution, version-roll migration), game-agnostic.
- `generic/` — tier 3: measurement & iteration discipline for any coding-agent work, no game/league.
- `null-tier.md` — the cuts (what was deliberately not packaged, with reasons).

## Provenance & gates

- All quantitative claims trace to server-side league A/B runs (Wilson CIs, N≥30) or decoded S3
  replays; each carries its own measurement context and date.
- Session-mined content that has not been independently re-confirmed against source is tagged
  **(session-derived, unverified)** throughout.
- Privacy gate applied at mining time: no secrets, tokens, credentials, or verbatim proprietary code.
- The raw extraction haul (transcript-derived candidates, verbatim tool source dumps) stayed on the
  author's machine and is **not** included in this bundle.
