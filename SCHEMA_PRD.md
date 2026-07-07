# Coworld Schema PRD — A Viable Tournament Loop

**Status:** draft for review. **Owner:** TBD. **Scope:** the Coworld schema (`coworld_manifest.json`) and the
component contracts it declares, framed around one goal — a tournament that is worth iterating in.

> This PRD documents the *ideal* system, not a scoped-down MVP. The working assumption is that endless coding
> agents will be thrown at the build until it works, so the job here is to describe what *should* exist, not to
> ration it. Some of it may turn out not to matter; that is fine — we cut later, from a complete picture.

## 1. North Star

The product is not "a tournament." It is **a closed improvement loop with a human-in-the-loop coding agent at
its center.** The tournament exists only to produce honest signal for that loop.

> A user downloads a starter package, improves the policy locally with their coding agent, uploads it, and it is
> measurably better in the tournament. Then they do it again.

The expected path is **not weight training** but a **coding agent + human editing the policy *as a program*.**
Nothing stops an agent from training a policy if it wants to — but an ML model is just a program that happens to
run on a GPU, and the platform offers it **no special support** beyond what any program gets. Every component in
this document exists to help the agent+human decide *the next code edit* and verify it helped — locally first,
then on the server.

### Viability gate (definition of done)

> **"I can make my policy better in a loop on my local machine, then upload it, and it is better."**

The gate has a hidden dependency that is itself load-bearing: *"and it is better"* requires that the loop can
**tell** it is better — locally before upload (a trustworthy A/B), and on the server after (trustworthy
standings). Signal fidelity is therefore a first-class requirement, even though "what winning means" is not.

## 2. The Loop

```text
LOCAL  (the agent runs this fast; the human runs it slow)
  1. Download the starter package: default player policy + tools + skills + reference field.
  2. Scrimmage the policy against the reference field  ->  episode bundles (experience).
  3. Review the experience: reporters + graders + diagnoser (skill tree) rank what happened
     and surface where the gains are.
  4. Plan, then edit the policy source.
  5. Verify locally: trustworthy A/B vs. the champion + a passing skill-regression gate.
     "It is better" locally. Loop back to step 2 until satisfied.

  --- upload --->

SERVER
  6. Placement: the commissioner decides where the policy lands. It may test the submission however it
     likes (a high-volume diagnostic burst, a draft, league rounds, ...) to place it before standings settle.
  7. League rounds (commissioner: volume x matchmaking) -> standings + per-episode bundles.
  8. Experience flows back (auto-run reports + downloadable bundles) into the next local loop.
```

The three user-facing pillars (from the founding interview):

- **(a) Build & optimize locally.** Download a starter package — a default player policy plus the tools, skills,
  and context a coding agent needs to improve it in a loop with the human.
- **(b) Submit & be scored meaningfully.** Submission and placement work; the scores the policy earns are
  *accurate and precise enough to be meaningful* to the developer.
- **(c) Learn from tournament experience.** The developer can understand what is happening as a *collection of
  experiences their policy is having with other policies*, and adapt.

## 3. Non-goals

- **No *special* support for training.** The expected loop is code editing, not weight updates. An agent may
  choose to train a policy, but an ML model is just a program that runs on a GPU; the platform gives it nothing
  beyond what any program gets.
- **Time-to-first-upload is not the optimization target.** Treating upload latency as the thing to optimize
  keeps resurfacing as a distraction. Think of it as **train (local) / test (server)**: the local loop is where
  iteration happens and must be high-signal, and it must feed a high-signal *post-upload* experience on the
  server. Time to first upload is not a good metric; we care about time to first high quality upload.
- **Defining "winning."** Ranking semantics (Elo vs bracket vs ladder) are the coworld developer's choice. The
  platform does not impose a standings model.
- **Replacing the existing manifest/role system.** This PRD *extends* the current `coworld_manifest.json`
  (see [`MANIFEST_README.md`](src/coworld/MANIFEST_README.md)); it does not start over.

## 4. Design principles (cross-cutting)

These recurred throughout the founding interview and govern every section below.

### 4.1 Platform = mechanism; coworld dev = curated defaults

Throughout this document, **"dev" means the coworld developer who owns the manifest** — they author or *approve*
every runnable and artifact a Coworld ships. The platform (and the schema) provide **mechanism and required
shape**. The **coworld developer** provides the
**baselines that "just work"** for their game, and may supply more on top. When asked "what's the unit of
attention?" or "what makes a segment worth attending to?", the answer is repeatedly: *it depends on the game —
the coworld dev must provide a good baseline.* The schema's job is to *require* that they do, and to define the
*contract* that baseline must satisfy.

### 4.2 Purpose-labeled runnable families (the keystone schema change)

Each role is not a single runnable but a **family** — a *list* of runnables, each **labeled with a purpose and
an output format.** See [§5](#5-the-schema-change-purpose-labeled-families) for the full proposal. This is the
structural backbone of the whole PRD.

### 4.3 Two cadences

Observability and tooling serve **two clocks at once**: the **coding agent** (fast cadence, machine-readable,
high-frequency iteration) and the **human** (slow cadence, visual, steering and spot-checking). Neither is
primary; both are crucial. Every render and report must be consumable by both.

### 4.4 Signal fidelity: "better appears better"

A trustworthy score = **volume × matchmaking.** Volume is the primary defense against noise — more episodes shrink
a score's variance; matchmaking puts a policy against opponents that actually *differentiate* skill. Placement must
be **stable** (similar policy → similar placement) and **differentiating** (reflects real skill, not noise); speed
and legibility are secondary.

But a score only differentiates skill if the **field exercises the right kind of skill**, and "skill" splits into
three tiers of temporal abstraction:

- **Mechanics** — the game-relative *actions*: the explicit action types the game recognizes (buy a scrambler, use
  it to scramble an enemy junction). An agent understands a mechanic if, given the goal, it can execute it.
- **Tactics** — the game-relative *options*: compact, branching sequences of mechanics that combine for more than
  the sum of their parts (subpolicies run to termination). Most games have a small set of **common tactics** a
  reasonable player is expected to know. Tactical space is rock-paper-scissors — did you pick the option advantaged
  against theirs?
- **Strategies** — *meta-tactics*: approaches that, over time, widen the breadth and depth of the tactics available
  to you relative to opponents (control grows your own tactical capacity; aggression denies opponents their slower
  tactics; diplomacy unlocks alliance tactics).

Games vary wildly across the tiers — Street Fighter is high-mechanical and high-tactical but nearly strategy-free;
chess is low-mechanical, high-tactical, moderately strategic. **The viability bar tracks the tiers in order:** the
default player policy must be competent across **100% of mechanic space**, **familiar with the common tactics**
(able to both play and respond to them) — **especially social mechanics and tactics** — and need **not** be strong
at strategy. A chess policy that can't castle (a mechanic) or can't answer a skewer (a common tactic) is the
canonical non-viable policy.

This bar is a **collective** property, which is why it can't be left to individual learners. Mechanics and tactics —
social ones above all — only pay off once enough of the field already plays them: the lone agent who learns to
*talk* in a population that ignores talk will correctly learn that talk is useless and stop, so the "talk metagame"
never ignites. *The world's best debater cannot sway a tiger.* So both the **base player policy and the seed
population** must already cover mechanics-and-tactics space (doubly so for social skill), or those dimensions never
become skill the score can reward.

*Verifying* that a custom commissioner actually meets the stable + differentiating bar is deferred to a future
base-league-health certifier (§12).

### 4.5 Experience → action is a workflow, not an artifact

No component magically emits "the edit to make." The loop is: agent + human **review experience together → plan**
(a `/plan`-style step, or ad hoc) **→ execute the edit → verify.** The schema's job is to guarantee a good
*review surface*, not to manufacture a decision.

## 5. The schema change: purpose-labeled families

Today the manifest declares one array per role (`reporter[]`, `grader[]`, `diagnoser[]`, …) where each entry is a
runnable identified by `type`/`id`/`image`/`run`. The required content of those arrays is fixed by the role
contract (e.g. "reporter must have at least one entry").

**Proposed change:** generalize every role array into a **purpose-labeled family.** Each entry gains:

| New field       | Declared by      | Purpose                                                                                          |
| --------------- | ---------------- | ------------------------------------------------------------------------------------------------ |
| `purpose`       | **coworld schema** vocabulary | Which *required purpose* this runnable fulfils (e.g. `narrative`, `creator_interest`). |
| `output_format` | **coworld dev**  | The shape of this runnable's output (mime/type + schema ref), so consumers know how to render it. |

And the **coworld schema declares, per family, the set of REQUIRED purposes** a valid manifest must cover. The
developer supplies one runnable per required purpose (labeled accordingly), declares each one's output format, and
**may add extra runnables with additional purposes** beyond the required set.

> **Spec 0061 supersedes this reporter example:** reporters are references
> `{"reporter": "owner/name@version"}` / `{"wasm": ..., "attributes": ...}`, not container runnables with an `image`.
> They fetch evidence via tools and emit typed output parts, not a bundle-URI → report-URI container contract.

```jsonc
// illustrative — reporter family with required purposes covered, plus one extra
"reporter": [
  { "type": "reporter", "id": "narrate",  "purpose": "narrative",  "output_format": "text/markdown", "image": "..." },
  { "type": "reporter", "id": "trends",   "purpose": "timeseries", "output_format": { "mime": "application/vnd.apache.parquet", "schema": "./schemas/timeseries.json" }, "image": "..." },
  { "type": "reporter", "id": "caster",   "purpose": "highlight_reel", "output_format": "text/html", "image": "..." }  // extra
]
```

This single abstraction resolves a stack of questions uniformly:

- **Required coverage is enforceable.** The schema can reject a manifest that fails to cover a required purpose,
  the same way it already requires a rules page and a play page.
- **Outputs are self-describing.** Consumers (renders, the optimizer, downstream graders) dispatch on
  `purpose` + `output_format` instead of hard-coding ids.
- **Devs extend freely.** Extra purposes are first-class, not bolted on.
- **It applies to *all* families,** not just graders — reporters, diagnosers, graders, even render views share
  the pattern. Required-purpose vocabularies per family are defined in [§6](#6-runnable-families).

**`output_format` representation.** A value is **either** a bare MIME string (opaque, route-only) **or** a typed
descriptor `{ "mime": ..., "schema": <JSON-Schema ref> }` (structured, so consumers can validate and render it
generically). **Rule:** any purpose whose output is **machine-consumed downstream** (the renderer-exposed
`event_log`, all diagnostics-port belief-types, grader scores, the `timeseries` reporter output) MUST use the
descriptor form with a schema; purely
**human-terminal** outputs (narrative markdown, highlight reels) MAY use the bare string. This keeps the cheap
one-liner where nothing parses the payload and full typing where tooling depends on it, and leaves a clean
upgrade lane to a named-format registry later without a breaking change. The same typing principle applies to
**every machine-facing interaction point** of a runnable — not only its final output but its inputs and any
served endpoints — so each interface a consumer depends on is self-describing.

`certification` is extended to assert that every required purpose is not just declared but **runnable** on the
smoke-test episode.

## 6. Runnable families

For each family: its **required purposes** (schema-declared), what the **dev supplies**, what the
**platform/schema supplies**, the **I/O contract**, and **status vs. prior art**. Families inherit the runnable
shape in [`MANIFEST_README.md` § Runnable Shape](src/coworld/MANIFEST_README.md).

### 6.1 game (live)

- **What it is (RL framing):** a runnable that **produces experience** in combination with a sufficient number of
  players. The game's outputs are **observations** (the players' inputs); the players' outputs are **actions**
  (the game's inputs) — the usual RL loop.
- **Lifecycle:** per-episode WebSocket server (`/healthz`, `/player`, `/global`, `/client/*`).
- **Dev supplies:** the game container; `config_schema`, `results_schema`; rules + play docs.
- **Platform/schema supplies:** the runtime contract via the **episode-runner**, which hands the game its
  `config.json` (conforming to the declared game-config schema, including the **injected player tokens**) and the
  per-URI artifact set (`results.json`, replay, logs) plus the **diagnostics-port** location, and the
  **observability** and **diagnostics-port** contracts that make observability possible
  ([§7](#7-observability-contract)). Browser-client surfaces (`/global`, `/clients/global`, `/clients/replay`)
  follow the existing GAME.md requirements.
- **Required of the game: observability, not a specific mechanism.** The game MUST give the viewer enough to
  reconstruct what happened and overlay live state — **either** deterministic **lockstep re-simulation** (re-run
  the episode and query live state) **or** a **rich replay file** that logs all the important states. Lockstep is
  one means to the end, not a hard requirement.
- **Game-side diagnostics.** Beyond player internals, the game MAY expose **secret/privileged state** for overlays
  (fog-of-war truth, hidden resources, opponent intent) so the viewer can show *what's really happening in the
  game*, not just in the player (§7.2).
- **Player-to-player communication is the game's job.** If a game lets players talk, the **game owns the channel
  and routing** as part of its observation/action space. The platform mandates **no particular** comms substrate,
  but it **does** provide a shared **LLM API** usable by both games and players, and building games or
  policies with LLMs is **encouraged** — an LLM or messaging substrate is just another program.
- **Replays are deterministic by definition.** A replay file plus its renderer reproduces the **same event
  series** and the **same queryable memory/diagnostics interfaces** every time (§7.1); reporters and humans
  consume that reproduction rather than a live process when convenient (§6.4).

### 6.2 player (live)

- **What it is (RL framing):** a runnable that **matches the game** — it consumes **observations** (its inputs)
  and emits **actions** (its outputs), which are the game's inputs.
- **Lifecycle:** per-episode; connects to the game's `/player` WebSocket as a client.
- **Dev supplies:** the policy **as a program** (the artifact the coding agent edits; cf. `cogamer/cvc/`).
- **Platform/schema supplies:** the **diagnostics port** contract — the policy exposes internal state as
  **typed belief-types** (generic carriers: *table-of-numbers*, *text*, *HTML*, each with a schema) that the
  replay viewer can **query during rendering** and draw as **configurable overlays**. The human toggles which
  beliefs overlay while watching. A **live port** (not a static file) is required because internal state can be
  large or streaming — e.g. a transformer's activations — which a flat file cannot carry; the port lets the
  viewer query just what it needs at a given tick.
- **`log()` is an optional runtime facility.** The policy **MAY** emit freeform notes (decisions, surprises, why
  it did X); the **episode-runner collects the player's stdout/stderr**, timestamps it, and exposes it
  post-episode for the coding agent + human to read during the optimize loop. These freeform notes are *not* the
  diagnostics port (which is structured, queryable belief-state).
- **Prior art:** `mettagrid.sdk.cogsguard.surface.CogsguardSemanticSurface` already projects raw observations into
  a **typed semantic surface** (`SelfState`, `KnownWorldState`, `SemanticEntity`, `SemanticEvent`, `TeamSummary`
  in `mettagrid.sdk.agent`) — exactly the belief-types the diagnostics port standardizes and overlays.

### 6.3 commissioner (contract defined, runtime pending)

- **Lifecycle:** per-round WebSocket (`/round`); see [`commissioner.md`](src/coworld/docs/roles/commissioner.md).
- **Dev supplies:** **two** capabilities — a **server commissioner** (drives league rounds) and a **local
  scrimmage** capability (run realistic tournaments locally). They may share one implementation or be distinct;
  both must be provided.
- **Platform/schema supplies:** the round protocol, the **volume guarantee** for scoring, and support for both
  local and server execution paths. **Matchmaking is the commissioner's job** — pairing for differentiation and
  coverage so scores are trustworthy.
- **Placement is entirely the commissioner's call.** It may test a submission **however it likes** to decide where
  it lands (which division/tier) — a diagnostic suite, a draft, a batch of league rounds, or any other heuristic.
  Which method works best is an **empirical** question, not one the schema prescribes.
- **Volume guarantee (conceptual).** Run **enough episodes per policy — sized to the game's noise — that score
  and placement uncertainty fall below a target precision**, with the platform supplying the execution capacity.
  Concretely, the platform grants the commissioner an explicit **episode allowance** — "you can use the runtime
  for N games per hour" — the way a stadium guarantees a league its game slots for the season.
  The point of placement is to enforce policy quality to ensure a healthy league ecosystem.
- **Open:** how identical the local league is to the server league is the **dev's choice**; the platform supports
  both. Placement must be **stable + differentiating** (§4.4); *verifying* that a custom commissioner achieves
  that is deferred to the future base-league-health certifier (§12).

### 6.4 reporter (contract defined, runtime pending)

- **What it is:** a **consumer of experience (or enriched experience) that produces reports.** *Experience* is the
  traditional stream of **(action, observation)** pairs — tuples of pairs for multiplayer. *Enriched experience*
  adds **player memory, game memory, player logs, and game logs** (each available via a queryable interface or
  materialized as states). A **report is the reporter's *action* and the experience its *observation*,** so
  reporters **chain indefinitely** — one reporter's report is experience the next can consume. Reporters operate
  over **one or many** episodes — cross-episode analysis (e.g. "find the lowest-performing replays") is a reporter
  function. The contrast with a **renderer** (§7) is in the **input types**: a renderer turns a (compressed)
  recording of interactions — a replay file — into graphics, sound, and reconstructed experience traces; a
  reporter turns experience traces into reports.
- **Required purposes (≥2):**
  - `narrative` — text description of the game's high points.
  - `timeseries` — crucial stats over the course of the game.
  - *(more allowed; e.g. highlight reels, news-caster cutdowns.)*
- **Typed event series are *not* a reporter purpose.** A game should **emit useful categorical events itself** (or
  expose them via the renderer's tick-queryable surface, §7.2). Re-deriving them inside a reporter is only worth
  doing when **hacking a game you don't control** into Coworld shape — otherwise it is wasteful.
- **Dev supplies:** at least the two above (+ extras), each with its `output_format`.
- **Platform/schema supplies:** the bundle-in / report-out contract (`COGAME_EPISODE_BUNDLE_URI` →
  `COGAME_REPORT_URI`) and the `event_log` parquet schema (`ts, player, key, value`) — emitted by the game and
  exposed via the renderer surface (§7.2), consumed by diagnosers, graders, reporters, and the optimizer. See
  [`reporter.md`](src/coworld/docs/roles/reporter.md).

  > **Spec 0061 supersedes this reporter contract:** a reporter is not a container with a bundle-URI → report-URI
  > contract. It is a submitted wasm component (or an external self-hosted program) that fetches evidence via tools and
  > emits typed output parts. See [`docs/roles/REPORTER.md`](src/coworld/docs/roles/REPORTER.md) for the shipped model.

### 6.5 grader (contract defined, runtime pending)

- **Required purposes (≥4):**
  - `creator_interest` — scalar "how interesting/useful was this episode" for ranking episodes (the existing
    grader purpose).
  - `player_experience` — **ranks experience by advantage for player-optimizers**: surfaces the segments/episodes
    with the most to gain, so the loop knows where to look. This is a **new, player-facing purpose**, distinct
    from creator-interest. **Signature:** `experience segment → score/description` — it reads experience that
    *already happened*. Contrast the diagnoser (§6.6), which maps a *policy → generated segments with pass/fail*.
  - `learning_signal` — grades a **single episode over time**, emitting a **dense or sparse** reward/score that
    marks **where important learning happened** (the moments worth the optimizer's attention).
    **Signature:** `episode → time-indexed reward (dense | sparse)`.
  - `group_relative` — grades a **batch of episodes on a relative basis**, GRPO-style: scores are **normalized
    within the group** (relative advantage), not absolute. **Signature:** `batch of episodes → per-episode
    relative scores`.
  - *(more allowed.)*
- **Dev supplies:** a grader per required purpose (+ extras); each labeled `purpose` + `output_format`.
- **Platform/schema supplies:** bundle-in / score-out contract; the purpose labels. **Scoring basis is the dev's
  choice** (VOR, Elo input, custom); the platform only guarantees volume. See
  [`grader.md`](src/coworld/docs/roles/grader.md).

### 6.6 diagnoser (reserved → promote)

- **Signature (vs. grader):** `policy → {experience segments, each with a pass/fail grade}`. The diagnoser
  *generates* experience by running the target policy against authored scenarios; the `player_experience` grader
  (§6.5) instead *reads* experience that already happened and scores it. Generate-with-verdict vs. read-and-score.
- **Required purpose:** `skill_regression_gate` — a **developer-provided tree of skills**: scenarios that test
  specific in-game abilities, each with a metric, a pass threshold, and seed/team-size coverage. This is the
  **regression gate** for the local loop. The schema requires *that a tree exists and conforms*; the dev authors
  the actual tree. Prior art: the **eval/training tree** in
  [`docs/specs/0027-cogsguard-training-tree-autocurricula.md`](../../docs/specs/0027-cogsguard-training-tree-autocurricula.md)
  (atomic mechanics evaluated independently, joined by prerequisites) aggregating the existing **Cogames
  `diagnose` diagnostics**. The handcrafted scenario fixtures in `mettagrid.sdk.cogsguard.scenarios`
  (`CogsguardScenarioPresets`) show how per-skill scenarios are *constructed*, but carry no thresholds — the gate
  is what adds the metric + pass bar on top.
- **Dev supplies:** the skill tree (scenarios + metrics + thresholds + coverage); optional richer assays.
- **Platform/schema supplies:** the schema/requirement for the tree, target-policy input
  (`COGAME_TARGET_POLICY_URI`), and the diagnosis output contract. See
  [`diagnoser.md`](src/coworld/docs/roles/diagnoser.md).

### 6.7 optimizer (reserved → promote)

- **What it is:** a **program** (in the Softmax sense — files-on-disk a runtime turns into a process; often
  markdown instructions for an LLM) **parameterized by experience or enriched experience** (direct from the policy
  or via a reporter, §6.4) whose function is to **convert a player policy into a better version** when given that
  experience. Optimizers split into **interactive** (a human in the loop for steering, guidance, and getting
  unstuck) and **autonomous** ("autoresearch" — just add compute). Autonomous optimizers are **far** harder, so in
  practice the requirement is met by an interactive one.
- **The requirement.** A viable Coworld ships **≥1 optimizer that any reasonably competent future user can run in a
  loop to repeatedly improve their policy — without first optimizing the optimizer or building missing tools.** At
  minimum an interactive optimizer is the **set of skills + advice** telling a coding agent how to use everything
  else here (renders, reporters, graders, diagnoser, local scrimmage, the A/B + skill-regression harness) to
  improve the player; that bundle is the floor, not the ceiling. (An autonomous submission would be a major ML
  advance and is welcome — but not expected.)
- **The optimizer stands alone; the IDE is recommended but optional.** The optimizer is the required,
  **agent-facing** surface and needs nothing else to satisfy the gate. The **IDE** — the **human-facing** surface
  for steering, inspecting, and spot-checking — is **recommended but optional**, and ships in the **SDK's coworld
  template** rather than being rebuilt by each dev.
- **Dev supplies:** game-aware skills/advice on top of the game-agnostic defaults — which verbs to run, which
  signals to trust, common failure modes, the local plan → edit → verify → upload recipe.
- **Platform/schema supplies:** the game-agnostic default skill set and the underlying verbs it orchestrates —
  builds on existing `cogames` verbs (`scrimmage`, `pickup` with its opponent pool + VOR, `diagnose`,
  `evaluate`), an optional default **human IDE** surface, and the shared **backend services** serious learning
  needs over time (policy store, experience store, and the like) — provided by the **coworlds package** and surfaced
  through **SDK templates**, *not* built by individual coworld devs. Prior art:
  [`Metta-AI/optimizers`](https://github.com/Metta-AI/optimizers). See
  [`optimizer.md`](src/coworld/docs/roles/optimizer.md).

## 7. Observability contract

Observability is **a contract on the game + player**, not a separate role. It is the single most under-specified
area today and the one the founding interview spent the most energy on.

### 7.1 Renders are replay-viewer variants over a reconstructable episode

A render reconstructs the episode from **either** deterministic **re-simulation** (lockstep) **or** a **rich
replay file** that logged the important states. When the episode is re-simulable, the viewer can additionally
**query the live agent during rendering** for its internal state; when it's a rich replay, that state must
instead be present in the file. Either path yields the same observability. The v1 render set is **four
information layers**:

1. `agent_pov` — **Agent POV** — what one agent actually observes.
2. `global_observer` — **Global observer** — all true world state.
3. `global_plus_pov` — **Global + agent POVs overlaid** — truth with each agent's perception drawn on top.
4. `pov_plus_beliefs` — **Agent POV + subjective beliefs** — POV plus diagnostics-port overlays (player- and
   game-side, §7.2).

The render set is itself a **purpose-labeled family** (§5): each view is a purpose; the dev may add more.

**Packaging is the dev's choice.** The schema requires **four invocable render runnables** (one per required
purpose) — effectively four command-line entrypoints. Whether those are four distinct programs or four modes of
one shared program **underneath is entirely up to the dev**; the platform only sees four runnables.

### 7.2 Requirements

- **API-driveable and embeddable.** Every render is fully controllable by an external API — **scrub, play,
  pause, step** like a good video player — and embeddable in other surfaces (league pages, agent tooling, any
  optimizer surface).
- **(Optional) live replay editing.** For the right kind of game, the viewer may let you **edit a replay live**
  — change what an agent does at a step and watch the effect ("this instead of that"). A high bar; **not
  required**.
- **Diagnostics-port overlays (player-side).** Belief-types are typed and schema'd so the viewer can query + draw
  them; the human configures which overlay while watching (§6.2).
- **Game-driven diagnostics (privileged overlays).** The viewer can also pull in **secret/privileged game state**
  the game chooses to expose (hidden truth, fog-of-war, opponent intent) and draw it as overlays — observability
  into *the game*, complementing the player-side port. The game declares which privileged signals it exposes; the
  human toggles them like any other overlay (§6.1).
- **Machine-readable, tick-queryable surface.** Beyond the visual render, the renderer exposes the reconstructed
  **event series and memory/diagnostics state as a structured surface queryable by tick/timestamp**, so agents,
  reporters, and other runnables can read exactly what happened at a given moment. Renderers are directly drivable
  by humans and by any runnable that knows the contract.
- **Serves both cadences (§4.3).** Visual for the human; the same underlying structured state queryable by the
  agent.

## 8. Coworld-dev artifacts (not runnables)

These ship *with* a Coworld but are not containers. The schema should require and locate them.

### 8.1 Reference field

The single most important missing component today: a **diverse, competent field** of opponents, packaged into the
base set, spanning a **spread of competence levels**. The bar (§4.4): the field must **make better policies appear
better.** It is **made with the same optimization tools shipped to players** — run the player loop to *produce*
strong reference policies, then package them; one investment, two payoffs (player tooling *and* the field).
**Building the field is the coworld dev's job.** Softmax's role is only to supply the dev with tools that make
producing it **easy and repeatable**; supplying the field with competent policies in order to be certified viable
is **solely the dev's responsibility** (for in-house coworlds the dev *is* Softmax, so this is academic — but the
responsibility still rides with whoever owns the manifest). The dev may populate it however they like — in-house,
via tournaments, or augmented by downloadable public or opted-in policies for local scrimmage. The local field is
necessarily **not** the full server field (can't distribute every submission); fidelity comes from the reference
ladder + a competence spread. **Viability is a gate a coworld attains over time, not an upfront hard
requirement** — non-viable submissions may still be uploaded and played.

### 8.2 Onboarding (especially for novel games)

So the agent+human can come up to speed fast enough to make good edits. **All three**, curated by the dev:

- An onboarding doc + **annotated example replays**.
- An **auto-generated mechanics summary** from the manifest/config.
- An **interactive sandbox** to poke the game and watch reference policies play.

(Extends the existing required `rules.md` + `play_*.md` docs in
[`MANIFEST_README.md` § Document Pages](src/coworld/MANIFEST_README.md).)

### 8.3 Accumulated wisdom — AGENTS.md + skills (recommended, not required)

Lessons that make a generic coding agent **competent on this game** rather than flailing — ideally
agent-consumable and **accumulating across iterations**, canonical home `AGENTS.md` + skills. This is **required of
Softmax's own internal projects but is *not* imposed on coworld devs**: a strong recommendation, not a viability
requirement. (cogsguard demonstrates structured `CogsguardLearning` records — `mettagrid.sdk.cogsguard.learnings`
— alongside prose AGENTS.md; the structured form is an optional dev choice.)

### 8.4 The starter package

The downloadable bundle **is the coworld itself** — the parts a developer needs to start (and re-enter) the loop.
The **minimum contents required to be certified viable** are: a **default player policy** (not a template — the SDK
provides dev templates, but the coworld ships players a working *default* policy), the **renderers** (required so
the service can display the coworld at all), the **reporters + graders + diagnoser** wired in, and an **optimizer**
that works against **at least one** base player policy. A **reference field** to scrimmage against is strongly
wanted — in some games the base policy *is* the field, but usually a small **library** of base policies is better.
**Programs must work out of the box:** the runnables run as documented in the coworld manifest, and if they need
installation the package ships an **install script** that sets the coworld up. Driving the optimizer and player
policy as documented **is the test for viability — the only test.** The kit should be **agent-drivable through a
handful of documented CLI/HTTP commands**, not dozens of manual installs.

## 9. Server ↔ local bridge (pillar c)

How league experience flows back into local iteration:

- **Both** paths, together: the server **auto-runs** reporters + the player-experience grader on league episodes,
  **and** the per-episode **bundles are downloadable** for local deep-dives.
- **Local repro of a server episode** (lockstep, same seed/opponents) is **the dev's choice**; the platform
  exposes the bundle either way.
- **Local-league fidelity** and **what the league surface shows beyond a rank** are **dev's choice** — they vary
  per game, so the platform provides mechanism and the dev curates (§4.1).

## 10. Role taxonomy (answering "5 roles or 15?")

The families resolve to **~8 runnable families** plus contracts and artifacts:

| Kind                        | Items                                                                                  |
| --------------------------- | -------------------------------------------------------------------------------------- |
| **Live runnables**          | `game`, `player`                                                                       |
| **Round-level runnable**    | `commissioner` (+ local scrimmage capability)                                          |
| **Post-episode families**   | `reporter` (≥2 purposes), `grader` (≥4 purposes), `diagnoser` (skill-tree gate)        |
| **Optimizer (+ optional IDE)** | `optimizer` (required; agent-facing) · **IDE** (recommended, optional; human-facing) |
| **Contract on game+player** | observability: 4 renders + diagnostics port (player + game-side)                                            |
| **Dev artifacts**           | reference field, onboarding, starter package (= the coworld bundle); AGENTS.md + skills *(recommended)* |

## 11. Viability gate & acceptance

The PRD is satisfied when, for at least one real Coworld:

1. A developer downloads the starter package and, **with their coding agent, edits the policy program** guided by
   renders + reporters + graders + diagnoser.
2. They **verify locally** that the edit is better — a trustworthy local A/B plus a passing skill-regression gate.
3. They **upload**, get **stable, differentiating placement**, and the league produces **meaningful** scores.
4. The uploaded policy is **measurably better** than the prior version — closing the loop — and league experience
   flows back to inform the next iteration.

**On the local success loop:** a viable Coworld ships a **functional optimizer**, and a functional optimizer needs
a way to **measure progress** — a **success loop**, which in general must be **local**. (A Coworld could in
principle lean on the server's generate-experience function, but that is *much harder* than shipping a decent local
measure.) Concretely this comes down to **having built player policies good enough to actually play the game and
respond appropriately to all common tactics** — one of the hardest parts of building a viable Coworld, and a major
focus for SDK support. The platform offers (used however the player likes) a paired/CRN A/B harness, per-opponent
breakdowns, and held-out seed pools, but **does not prescribe the statistic** — what counts as "better" is the
player's call.

## 12. Open questions

- **Diagnostics-port belief-type registry.** The generic carriers (table/text/HTML) plus how game-specific typed
  beliefs register with the viewer (now spanning **both** player-side and game-side privileged signals, §7.2).

### Future directions (out of scope for v1)

- **Base-league-health certification.** A future certifier that validates **league health** — runs the
  **commissioner** against the **provided suite of base player policies** and checks the field/placement is
  healthy — complementing the v1 certifier's focus on the optimizer loop. This is the home for **verifying custom
  commissioners' ranking logic** (candidate approaches: clone-resubmit landing-check, repeated out-of-competition
  diagnostic episodes, bayesian-until-convergence ELO) and a **fully enforced league-wide volume guarantee**.
- **Staging → promotion lifecycle.** Auto-promoting a game from staging once a diverse, competent field exists
  belongs to base-league-health work, not v1.

## See also

- [`src/coworld/MANIFEST_README.md`](src/coworld/MANIFEST_README.md) — current manifest field reference (the base
  this PRD extends).
- [`src/coworld/docs/roles/OVERVIEW.md`](src/coworld/docs/roles/OVERVIEW.md) — how the roles compose; artifact flow.
- Per-role contracts under [`src/coworld/docs/roles/`](src/coworld/docs/roles/).
- [`src/coworld/EPISODE_BUNDLE_README.md`](src/coworld/EPISODE_BUNDLE_README.md) — bundle contract consumed by the
  post-episode families.
- Prior art: the **cogsguard SDK** at `mettagrid.sdk.cogsguard`
  (`packages/mettagrid/python/src/mettagrid/sdk/cogsguard/` — `surface.py`, `learnings.py`, `scenarios.py`; the
  `cogames.sdk.cogsguard` paths are now re-export shims), `packages/cogamer/src/cogamer/cvc/`,
  [`docs/specs/0027-cogsguard-training-tree-autocurricula.md`](../../docs/specs/0027-cogsguard-training-tree-autocurricula.md),
  [`Metta-AI/optimizers`](https://github.com/Metta-AI/optimizers).
