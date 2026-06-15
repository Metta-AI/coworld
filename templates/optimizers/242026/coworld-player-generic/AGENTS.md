# AGENTS.md — coworld-league player optimization (always-on)

This is the **coworld-player tier**: the always-on guardrails for optimizing any scripted or
LLM-driven player (a "bot" you control end-to-end) for any Softmax **coworld** league — a hosted,
adversarial, mixed-role matchmaker where you ship a container into a seat and read scores back. It
**applies the generic tier** (pure measurement and iteration discipline — Wilson/CI verdicts,
statistical power, refutations-as-results, root-cause-not-band-aid, fail-loud) and is in turn
**specialized by a project tier** that carries one specific game's numbers, IDs, source-line cites,
and commands. Keep this file loaded; it shapes every hypothesis. The generic principles it leans on
are stated **only** in the generic tier — this tier names the coworld-specific *shape* and points
there for the rationale. The concrete endpoints, league/division IDs, bot source, and exact commands
live **only** in the project tier.

Two companion guides expand the operational detail:
`guides/coworld-league-eval-methodology.md` (the server-side forced-role A/B + crux + promotion +
roster-resolution + version-roll methodology) and `guides/coworld-optimization-loop.md` (the loop
shape). The standing cross-league craft — protocol-family matching, the full role/slot gate, terminal
evidence, named negative controls, blue/green lanes — lives in `guides/cross-coworld-craft.md`; this
file does not restate it.

## The eval surface is a real hosted league, not a lab

The thing that makes coworld optimization its own discipline: **competitor images are private and
cannot be pulled or run locally.** Only the league server holds them and can run a game by policy
reference. So the faithful comparison is always **server-side** — your bot in one seat, real
opponents in the others — never a local self-play scrimmage. A local lab is at best a mechanism check
(does the bot connect, does a code path fire); it can never measure strength against a field it
cannot instantiate. Build your measurement around the server's counterfactual-match engine, not
around reproducing the league on your machine.

## The scoring & win model shapes every hypothesis

You cannot pick a lever without knowing how the game and the leaderboard actually score. Before any
optimization, pin down — from the game's own source, not its docs (which are often empty stubs) —
these four facts, then keep them loaded:

- **Seat/role distribution.** Which roles exist, how many seats each fills, and therefore which role
  dominates the leaderboard mean. A role you occupy in a minority of seats can only move a minority of
  your score — correctness in the *common* role usually beats cleverness in the rare one. (The project
  tier states the actual counts.)
- **The exact win/terminal condition.** What ends a game and what counts toward it — and whether two
  superficially different events (e.g. an elimination vs a wrongful removal) are mechanically
  identical. A mechanic that looks purely beneficial is often double-edged once you read the terminal
  condition. Read the source; verify empirically where the source is ambiguous (a second code path can
  invalidate a source-only conclusion).
- **What the lever depends on.** Many games flip between regimes depending on the field (e.g.
  decided by task throughput in one field, by eliminations in another). The right lever is the one for
  the regime you **measured**, not the one that sounds good in the abstract.
- **How the leaderboard aggregates.** Official rank is almost always a slow, large-n lifetime mean
  over mixed-role rounds, not a single-game score. That means **durable rank is time-gated, not
  code-gated** once your bot is strong: a forced single-seat A/B isolates whether a *change* helped,
  but does not linearly predict league position. Judge **attribution** from A/B deltas and **position**
  only from accumulated rounds. (See the generic tier for why point estimates lie at small n.)

## "Champion"/leaderboard-slot is a label, not a quality signal

The single most common misread in this family of leagues. A user typically owns **two player slots**,
and the league's term for the leaderboard-scoring slot (often "champion") means exactly *"this is the
slot whose rounds count toward the board"* — **not** winner, not #1, not "the good one."

- Judge any policy by **its measured score vs the field**, never by which slot-label it carries.
- The official board lists only slots holding that label; roster churn (submit/retire/rotation) can
  silently clear the label and drop you off the board entirely. After **any** roster change, re-read
  the membership state and re-confirm your slot is still listed and still labelled.

## Measurement discipline is generic — apply it here, don't restate it

The verdict rule (non-overlapping confidence intervals only), the minimum-n floor, the
extend-don't-re-roll rule, pooling same-direction deficits, and "refutations are results" are **stated
in the generic tier** — they are not coworld-specific and are not repeated here. What *is*
coworld-specific:

- **A "crux" is a hypothesis about the CURRENT policy, not a permanent record.** A crux is a
  reproducible config where a named rival out-scores you. Every policy update re-runs **all** open
  cruxes — the sweep doubles as the regression guard; close the ones the update fixed. (The crux
  *construction* mechanics are in `guides/coworld-league-eval-methodology.md`.)
- **Calibrate the instrument against the live field before trusting a number.** A metric pinned at a
  structural floor or ceiling (e.g. a game length so short the cooperative role can never win, or a
  field so weak the win rate ceilings near 100%) measures nothing. Verify the headline metric is in a
  *movable* range for the baseline; if it's pinned at an extreme, change the regime (stronger
  opponents, a difficulty knob in the request body, a non-binary metric) — not the bot.

## Two-slot live A/B and the promotion rule

Run exactly **two** live policies — the labelled (champion) slot plus one rolling **experiment** slot.
A third live policy, or a stale experiment, dilutes each slot's per-round sample; the pair is a free
live A/B at half the data rate each. (This is the league-mechanics specialization of the generic
blue/green-lanes idea in `guides/cross-coworld-craft.md` — derive the lane from live rank, never
churn-rename.)

- Submitting a new policy qualifies it **into the experiment slot**; it does **not** auto-displace the
  labelled slot. Even a candidate that is only **non-inferior** in constructed tests belongs in the
  experiment slot, because the live round mix samples configurations your constructed ladder never
  runs.
- **Promote only when BOTH hold:** (1) **live-ahead** — the experiment's clean-round mean (drop
  collapsed/degenerate rounds from both sides first) sustainably beats the labelled slot's, judged
  variance-aware over a **wide** window; AND (2) **constructed-dominant** in the seeded crux/ladder
  A/Bs.
- **A windowed significance gate alone can NEVER fire a promotion.** As the experiment starts winning,
  the league rotates rounds toward the leader and the *loser's* in-window sample evaporates, so the
  test starves itself before it can trip. Decide on the **totality of evidence**, never on a single
  window test reaching a threshold.
- **A constructed-test win does not guarantee a live win.** Live rounds sample the **whole** division,
  not just the top — a top-field-only ladder overweights exactly the games the live mix rarely plays.
  Before fielding, run **live-mix replica arms**: paired candidate-vs-current arms over **randomized
  division-mix fields** (sample distinct live members client-side, fresh draw per chunk, varied seeds).
  This gate is mandatory; a candidate can pass every constructed A/B and still lose points live. (See
  `guides/coworld-league-eval-methodology.md` for the construction.)

## Re-resolve live state every launch — it rots within hours

An active league churns underneath you: it rolls policy **versions** mid-session, standings move
hourly, and the coworld package itself can roll without notice.

- **Re-resolve the live roster immediately before EVERY launch**, by player **name → current live
  reference**, never by a cached version label or a reference pulled from an old round result (those
  go stale and are rejected). Versions **flip**, not just advance — a reference can die and go live
  again within the hour. Pooling across chunks is valid **only** when the field references are
  identical across the pool.
- **Every verdict is a within-battery paired comparison.** Re-run the incumbent as a **same-era
  control** on the *current* field whenever a result looks alarming — never compare a new build against
  a baseline measured hours ago. A "weak-field" baseline can become a "strong-field" one for the *same
  policy* within a day as the bottom of the division strengthens.
- **Refresh standings before every comparator batch.** A new top player can surge while you're still
  reasoning from the morning snapshot.
- When the coworld package itself rolls, stop and run the version-roll migration before trusting any
  local number — see `guides/coworld-league-eval-methodology.md` (and the project tier for the exact
  source-paths to diff).

## Fail loud — no silent fallbacks, no result caching

- **A forced-role seat assignment that the server rejects must FAIL LOUDLY** and surface the
  validator message. The explicitly-banned anti-pattern: a fallback that quietly assigns roles some
  other way (e.g. from the seed) and post-filters episodes — that silently changes **which role is
  measured** and corrupts the A/B with no error. A forced-seat rejection is a *designed* hard failure,
  not a condition to paper over. The acceptance gate on a new coworld version is one real low-N A/B;
  if the server rejects the role-forcing config, STOP and surface it.
- **Never cache or dedupe match results.** The same pairing must be re-runnable arbitrarily many
  times — that is how you accumulate n. A wedged participant must fail loud on a stall-grace budget,
  not wait forever. (The fail-loud *principle* is generic; the seat-forcing and re-runnability
  *applications* are what this tier adds.)

## Keep the loop alive, and gate league-visible actions

- **In-flight matches are the heartbeat.** If none are running and none were created recently, the
  loop is stalled regardless of how healthy the board looks — keep probes or extensions running and a
  liveness monitor up (count fresh local analysis artifacts as liveness too, since build and analysis
  phases legitimately make no requests). Background pollers and subagent lanes die silently across
  session restarts; checkpoint each lane's state to a file so a relay agent resumes losslessly. A
  client-side poller crash is **not** a backend failure — re-fetch the existing request id, never
  resubmit.
- **League-visible actions are gated on explicit user approval** and done only by the lead agent,
  never a subagent: submitting a policy, retiring one, swapping the labelled slot, and any externally
  visible action (filing a bug, anything beyond the private optimization tracker). A subagent that
  ships a policy unprompted can go unnoticed for a day — audit the **full** membership roster, not a
  name-filtered view.

## Verify before porting a rival's behavior

The most expensive class of wasted work is re-implementing something your bot already does, or copying
a rival move that doesn't carry its payoff. Before proposing any port:

- **Read your own bot first** and confirm the technique isn't already present. Mature scripted players
  usually already implement the "obvious" moves.
- **Measure the existing fire-rate.** A "missing" technique that, once instrumented, fires zero times
  in the regime that decides games is not a lever — it's a distraction.
- **Classify the rival behavior before copying it** — bundled-cost vs system-dependent vs
  surface-vs-mechanism (the taxonomy and what each means are in the generic tier; don't restate it).
  The coworld-specific way to settle it cheaply: **ablate the suspected mechanic for both bots** via
  the request's config-override surface and re-run paired arms. One small-N ablation can prove a
  rival's entire edge is a single mechanic — answering what weeks of behavior-copying could not.

(For the project's own bot architecture and the levers already measured-dead, see the project tier's
guides before proposing anything.)
