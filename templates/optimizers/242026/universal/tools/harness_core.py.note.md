# harness_core.py — note

**What it does.** The small pure-logic core shared by the CLI and dashboard: the
statistics and the seed-deterministic forced-role configuration. No I/O, no
network — just the math and config the rest of the eval stack reuses.

**Key entry points.**
- `wilson(k, n)` — `(point, lo, hi)` Wilson score interval (z=1.96); the verdict
  math behind every A/B comparison (a candidate "wins" only when its CI clears the
  baseline's, hence the `INCONCLUSIVE (CIs overlap)` outcome).
- `forced_imposter_slots(seed, *, player_count=8, imposter_count=2)` — the
  deterministic imposter-seat selection (`random.Random(seed).sample`), so both
  A/B arms share an identical seed-pinned seat layout.
- `slot_role_config(imposter_slots, ...)` — turns the chosen imposter slots into
  the per-seat `[{"role": ...}]` list the request's `game_config_overrides` use.
- `ROOT` / `CREWRIFT_REPO` — project + bot-repo path resolution (env-overridable
  via `CREWRIFT_ROOT` / `CREWRIFT_REPO`), used across the harness for file paths.

**Why it matters to the loop.** It is the trust anchor of the eval: the forced-slot
config makes the two arms directly comparable (same seeds, same imposter seats),
and `wilson()` is the single definition of "is this difference real?" reused by
`league_eval`, `metrics`, and the dashboard.

**Status: CURRENT.** Foundational module of the current server-side eval stack;
imported by league_eval, episode_runner, and dashboard.
