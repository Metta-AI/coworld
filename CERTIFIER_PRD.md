# Coworld Certifier PRD — Certificates for a Viable Loop

**Status:** draft for review. **Owner:** TBD. **Scope:** the *certifier* — the thing that evaluates a Coworld over
time and issues certificates. Companion to [`SCHEMA_PRD.md`](SCHEMA_PRD.md), which describes the Coworld itself.

> This PRD documents the *ideal* certifier, not a scoped-down MVP — same framing note as the schema PRD. We
> describe what *should* exist and cut later from a complete picture. Where today's code already implements a
> piece, we say so ([§9](#9-what-exists-today)).

## 1. North Star

A Coworld certifier answers one question for a stranger: **does this Coworld have what it takes to be viable** —
to be a *successful* Coworld in the Softmax Universe? The schema PRD's north star is a closed improvement loop;
the certifier's is **a citable fact about whether that loop actually closes**, cheap for anyone to check before
they commit their own effort.

A certificate is issued **at a point in time**: it asserts something about the Coworld *relative to Softmax and
this certification process, as they stood on that date*. The fact itself is immutable, but it can **go out of
date** — if the Coworld, Softmax, or the certification process change, an older certificate may no longer
describe the current world ([§3](#3-the-certificate) makes this precise).

A given certifier issues grades over **some number of degrees** ([§5](#5-category-and-degrees)). *This* certifier
is currently focused on the viability of the **core optimization loop**: *generate experience, analyze
experience, modify policy, repeat.*

## 2. Certifier : grader :: integrator : differentiator

A **grader** is a differentiator: a one-shot function `episode → score`. A **certifier** is an **integrator**: it
uses *many* graders (and runnables, and a human) **adaptively over time** to evaluate a Coworld in an interactive,
multidimensional way, and emits a **certificate**. The grades are the integrand; the certificate is the integral.

The grades themselves may be retained as a **transcript** attached to the certificate, but they are not the
certificate. The certificate is the summary fact: *this thing reached this standard, attested by this authority.*

## 3. The certificate

A certificate is an **immutable, content-addressed fact**. It is not a mutable status; it never "expires" or
"invalidates." It asserts:

> Certifier ⟨authority **@digest**⟩ attests that the certified ⟨Coworld **@hash**⟩ met ⟨transcript **@hash**⟩ —
> **matriculated @ T₁**, **graduated @ T₂** (or *did not graduate*).

**The certification job *is* the certificate.** Rather than serialize this as a standalone fat record, the
attestation lives in the immutable certification `JobRequest` and its result: the job pins the certifier image
digest and the resolved `@sha256:` digest of every Coworld image it ran (it must, to launch them), and its result
holds the transcript — the ordered `StepResult`s plus the matriculation and graduation timestamps. The thin
`certification_requests` row points at that job (`certification_job_id`) and caches the result in `results`; a
Coworld's *current* certified standing is the `coworlds.latest_certification_request_id` pointer, set to its
latest graduated attempt. The fields below are therefore *reachable from the job*, not columns of a certificate
object.

Field by field:

| Field | Where it lives |
| --- | --- |
| **Certifier identity (authority)** | The certifier **image digest** the job pinned — the exact code + exam (transcript) that ran. Stronger than a module hash, and recorded on the job by construction. |
| **Certified identity** | The Coworld at a content hash on a date — reachable via the job's `coworld_id` and the resolved image digests it ran. A changed Coworld is a *different* certified identity (a new attempt). |
| **Transcript** | *What was checked* — the certifier's ordered procedure plus its per-step `StepResult`s (§6.1), in the job result (cached in `certification_requests.results`). |
| **Matriculation time T₁** | Recorded in the job result when the `matriculate` step passes. |
| **Graduation time T₂** | Recorded in the job result when the degree is conferred — or absent if it was not. |
| **Category + degree** | The category and degree level reached ([§5](#5-category-and-degrees)). |

**Expiration and good standing are properties of the *reader*, not the certificate.** A certificate is simply
true. Whether you accept an Optimizable cert that is 90 days old, or one on a hash the Coworld has since
superseded, is *your* policy — and the `coworlds.latest_certification_request_id` pointer makes "what is this
Coworld's current standing" a single lookup. The certifier emits true facts; the market decides what is still
relevant.

## 4. Lifecycle: matriculation → grading → graduation

Modeled on a university. A Coworld moves through three stages, and certificates can be issued at each.

- **Matriculation** — the **static** check: "this is the kind of thing we certify." The manifest conforms to the
  Coworld schema. The certifier will not begin grading otherwise. A **certificate of matriculation** can be
  issued on its own.
- **Grading** — while matriculated, the certifier **interacts** with the Coworld over time: automated integrity
  runs plus, for higher degrees, a human examination ([§5](#5-category-and-degrees)). This is the integrator at
  work.
- **Graduation** — a **degree** is conferred, issued as a **degree file** (§6.4) and recorded in the certificate,
  which now carries both T₁ and T₂. A matriculation certificate issued for a Coworld that has *not* graduated
  reads "matriculated, did not graduate" and confers no degree file.

There is no separate mutable "good standing" flag. Standing is just **the pattern of certificates over time**: a
matriculation certificate at time T is the true statement of standing at T; a later graduation is a later, also-
true certificate.

## 5. Category and degrees

A **category** is the subject (*what* the thing is); a **degree** is the level of standing reached within it.

- **Category = `Coworld`** — the subject. (Room for other categories later; today there is one.)
- **Degrees, ascending:**
  - **Matriculated** — statically a Coworld (schema conforms). Admission, not a degree.
  - **Executable** — the parts actually run end-to-end and emit output. **Fully automated**; machine-checkable
    integrity. This is the robot's to grant alone.
  - **Optimizable** — the **viability floor**: the loop closes *once*. A human examiner, using **only** the
    Coworld's shipped parts (cold, self-bootstrapping), drives the optimizer to **one verified improvement** and
    attests the loop closed. That attestation is trustworthy only because the reference field exercises the right
    skill, so the examiner can *tell* better from worse (§6.3; §4.4 of the schema PRD). First-tier viable.
  - *Higher (stronger-viability) degrees deferred.*

The load-bearing cut is **not** differentiator-vs-integrator (that is method); it is **auto-gradable correctness
vs. human-judged value.** Executable is what a robot can certify alone. Optimizable is where a human examiner is
**irreducibly in the loop** — because "make the player policy better" is not yet reliably auto-researchable, so no
automated check can stand in for the human attestation that the loop closed.

## 6. Transcript and degree files

Two things matter at graduation, but they live differently:

- the **transcript file** — *what was checked*: the certifier's procedure for one degree in one mode, the ordered
  list of declared steps (1, 2, 3, …) it runs. It is frozen into a hostable, URL-addressable, hashable artifact,
  and hashing it is what gives a degree a **fixed, citable meaning** that survives even as the certifier's code
  evolves. The transcript's *declared* form is hashed for meaning; the *run record* — the per-step `StepResult`s
  (§6.1) — is recorded in the certification job's result, not stored as a separate hashed file.
- the **degree file** — *what was earned*: the short conferred credential (§6.4), the diploma that names the
  degree a graduation confers. It is a **human-readable rendering of the attestation, regenerated on demand** from
  the job result + the `coworlds` pointer ([§3](#3-the-certificate)) — there is one degree per category named by
  the contract version, so the credential is derivable, not a separately-stored content-addressed artifact.

This section specifies the transcript file's format (§6.1) with two illustrative transcripts (§6.2–§6.3), then
the degree file (§6.4).

### 6.1 Format: markdown is canonical

A transcript file can be a program, a typed schema, or a spec — whatever is convenient — but the **canonical form
is markdown with a structured, ordered step list**, because the transcript must serve the same two cadences as
everything else (§4.3 of the schema PRD): a human reads it cold to understand what a degree means, and the
certifier executes it. A program would be opaque to the human; a bare schema would be opaque to the reader. Markdown
with stable step ids is both, and it hashes and hosts as-is.

Each step has two halves: the **declaration** (frozen in the markdown, part of the hashed meaning) and the
**result** the certifier records when it runs the step.

**Declared fields** (in the transcript markdown):

| Field | Purpose |
| --- | --- |
| `id` | Stable identifier the certifier maps to an executor (and the transcript keys off). |
| `kind` | `auto` (robot runs it) or `human` (examiner performs + attests). |
| `checks` | The claim this step establishes. |
| `pass` | The pass criterion — what counts as satisfied. |
| `how` | How to run/perform it, written so a cold agent or human can do it unaided ([§7](#7-self-bootstrapping)). |

**Result fields** (the `StepResult` the certifier records per step at run time):

| Field | Purpose |
| --- | --- |
| `id` | The declared step this result is for. |
| `kind` | Carried from the declaration. |
| `status` | `running` (announced, in progress), `pass` (the step's `pass` criterion was met), or `fail` (it was not). |
| `failure_reason` | On `fail`: a typed, machine-readable reason the step did not pass. For the runtime steps that wrap a dispatched episode, this is the episode error taxonomy (`player_error`, `game_unhealthy`, `results_malformed`, `replay_unloadable`, …); for the static steps it is the step's own failure class. Absent on `pass`. |
| `feedback` | On `fail`: a human-readable explanation — *what* failed and, where the certifier can tell, *how to fix it* — written for the Coworld developer reading the transcript to understand why their Coworld did not graduate. Absent on `pass`. |

The certifier maps each `id` to its executor; the markdown is the source of truth for *meaning*, the code is the
*implementation*. When the **declared** fields change, the file's hash changes, and that is a new definition of
what the degree requires — old certificates still point at the old hash and stay true. The **result** fields are
not part of the hashed meaning; they are the run record, and a transcript with a `fail` step is itself the
attestation that the Coworld did not graduate — the failing step, its `failure_reason`, and its `feedback` say
exactly where and why.

Executable is still **binary**: a degree is conferred only when every step's result is `pass`. Recording a `fail`
result does not soften that — it makes the *non*-graduation legible. The certifier records the failing step's
result, then stops; later steps that never ran simply have no result.

### 6.2 `coworld-executable.transcript.md` (Executable) — illustrative

```text
 1. matriculate       [auto]  manifest conforms to the Coworld schema        pass: schema validates
 2. source-resolves   [auto]  every source_url resolves + has a Dockerfile   pass: all resolve
 3. images-reachable  [auto]  every declared image is pullable/inspectable   pass: all reachable
 4. fixture-conforms  [auto]  certification game_config validates against    pass: schema validates
                              config_schema (before any container launches)
 5. smoke-episode     [auto]  game + certification players run one episode   pass: episode completes
 6. results-conform   [auto]  results validate against results_schema        pass: schema validates
 7. replay-present    [auto]  a replay artifact was produced                 pass: file exists
 8. replay-loadable   [auto]  the game re-loads the replay and serves it     pass: /replay emits a
                              over /replay (a second game-only launch)            non-empty message
 9. players-run       [auto]  every declared player actually starts on the   pass: each declared player
                              smoke episode (not just declared/resolved)         ran, not just resolved
10. supporting-roles  [auto]  each declared supporting runnable runs and     pass: every declared
                              honors its contract (per-runnable)                  supporting role passes
```

The split into independently-attributable steps is deliberate: `smoke-episode` only *runs* the episode, and
`results-conform` / `replay-present` / `replay-loadable` are separate gates, so a transcript `fail` names the
exact contract that broke rather than collapsing every runtime problem into "episode failed" (§6.1
`failure_reason`). `players-run` proves the player role actually launched (the game is already proven by the
episode completing). `supporting-roles` (step 10) is per-runnable: today it validates the **reporter** references
(updated for spec 0061: `validate_reporter_references` in `certifier.py` checks each manifest reporter reference
statically — no Docker run, no report zip — and the server-side supporting-roles probe *resolves* the reference
against the registry rather than running a container) and a **commissioner** protocol probe; **grader** and
**diagnoser** have no run harness yet, so a Coworld declaring them is not failed on their account until those
harnesses exist (their slots in this step are inert, logged, not graded). The **optimizer** is never exercised
here — it belongs to Optimizable (§6.3).

### 6.3 `coworld-optimizable.transcript.md` (Optimizable) — illustrative

```text
1. requires-exec   [auto]   holds a current Executable on this hash       pass: Executable cert present
2. cold-bootstrap  [human]  examiner brings up each shipped part using    pass: every part runs from
                            ONLY its own self-description (--help, docs)        its own instructions, cold
3. one-improvement [human]  examiner drives the optimizer to a single     pass: a trustworthy local A/B
                            edit and verifies it is genuinely better            shows the edit is better
4. attest          [human]  examiner signs the attestation; transcript    pass: signed attestation +
                            (session log, before/after, episodes) attached      transcript recorded
```

The examiner is an **agent of the certifier**, not an independent party we must standardize (§8). The expensive
operation is the human examination; binding it to the Coworld hash means a loop-relevant change is simply a new
certified identity that earns its own Optimizable — no "re-validation," just a new immutable fact.

**What makes step 3's signal trustworthy.** The `one-improvement` A/B is only believable if "better" is
*detectable* — and that is a property of the Coworld, not the examiner. Per §4.4 of the schema PRD, the reference
field (§8.1 there) must make better policies appear better: competent across **100% of mechanics** and
**familiar with the common tactics** (social ones above all), with **strategy not required**. If the field lacks
that coverage the A/B cannot differentiate skill and Optimizable cannot honestly be earned — so the examiner's
cold-bootstrap of the field and harness is implicitly a check on **signal fidelity**, not just on whether the
parts launch.

### 6.4 `coworld.degree.md` (the conferred degree) — illustrative

Where a transcript records *what was checked*, the **degree file** records *what was earned*: the short, citable
credential a graduation confers. It is the diploma — "this Coworld is **Executable** and **viable**" — a degree in
Coworld viability issued by the Softmax Universe certification process, addressable by its own hash.

```text
Coworld:    ⟨hash, date⟩
Authority:  Softmax ⟨authority hash, date⟩
Degree:     Executable + Optimizable (viability floor met)
Conferred:  T₂
Transcript: coworld-optimizable.transcript.md ⟨hash⟩
Statement:  This Coworld's core optimization loop closes — its parts run end-to-end, and a human examiner
            drove the optimizer to one verified improvement.
```

The degree file is what a stranger cites in one line; the transcript is what they open when they want the
evidence behind it. A matriculation-only certificate confers no degree file.

## 7. Self-bootstrapping

Every transcript-file step that touches a Coworld part assumes that part **teaches its own use** to a cold-start
human or agent — via `--help`, README/markdown, protocol docs, AGENTS.md + skills. The Optimizable examination is,
in large part, a **test of that property**: if the examiner cannot bring a part up from its own self-description,
the loop has not closed for a stranger, and Optimizable is not earned. The certifier itself is held to the same
bar — it must explain its own use, degrees, transcripts, and degree files to a cold operator.

**Required vs. optional parts.** The bootstrap gate binds to the **required, agent-facing** surfaces — the
optimizer above all (§6.7 of the schema PRD), which must run cold from its own skills + advice without first being
optimized or having missing tools built. **Optional, human-facing** surfaces do not block the degree: the **IDE**
is recommended but optional, so its absence is never a failure, and the examiner may drive the optimizer
**interactively** (via the IDE if present) or **autonomously** — an interactive optimizer satisfies the floor.

## 8. Trust model: Softmax is the university

By fiat: **Softmax is the university; its certifiers are definitionally correct.** There is no external rubric or
accreditation chain to design. The certificate's "certifier identity" is simply *which Softmax authority @hash
issued it*. Disagreements are handled **out-of-band** — we are not hard to contact. This is what lets the human
Optimizable attestation be trustworthy without a standardization apparatus: the examiner acts as the authority,
and the authority is correct by definition within the ecosystem.

## 9. What exists today

`coworld.certifier.certify_coworld()` runs the **Executable** procedure end-to-end, transcript-driven: it parses
`coworld-executable.transcript.md`, executes an executor per step id in order, records a `StepResult` per step,
and asserts the executed ids equal the declared ids. The step machinery (`TranscriptStep`, `StepResult`,
`CoworldTranscript`, `load_executable_transcript`) and the executors for `matriculate`, `source-resolves`,
`images-reachable`, `smoke-episode`, `results-conform`, `replay-present`, and `players-run` exist today.

The supporting schema and shared contracts are also in place:

- **Schema (merged).** The certification attestation is the job + a thin `certification_requests` row + the
  `coworlds.latest_certification_request_id` pointer (§3); the certifier image digest a contract version points at
  is the authority.
- **Episode error taxonomy (merged).** The episode runner raises typed errors — `player_error`, `game_unhealthy`,
  `game_contract_violation`, `results_missing`, `results_malformed`, `replay_missing`, `replay_unloadable`,
  `episode_timeout`, `crash` — which become the `failure_reason` on a failing runtime step (§6.1).

The near-term job from here:

- **(a)** split the fused smoke-episode call into the independently-attributable steps 5–8 (`smoke-episode` runs
  only; `results-conform` / `replay-present` / `replay-loadable` are their own gates), add `fixture-conforms`
  (step 4) and generalize `supporting-roles` (step 10) to the reporter reference-validation
  (updated for spec 0061: static reference validation, no container run) + commissioner probe;
- **(b)** record per-step `fail` results with `failure_reason` + `feedback` (§6.1) instead of raising raw, and
  drop the vestigial standalone certificate/degree-file objects in favor of the job-as-attestation (§3);
- **(c)** wire the Observatory path — dispatch the smoke episode as a `coworld_episode` job, read back its run
  digests, and on graduation set the `coworlds` pointer;
- **(d)** add the human-in-the-loop Optimizable examination on top. Optimizable has no automated implementation
  today, by design.

Grader and diagnoser run harnesses do not exist yet, so step 10 covers the reporter and commissioner only
until they do (updated for spec 0061: the reporter check is static reference validation, not a container run).

## 10. Open questions

- **Certificate artifact + transcript shape.** *Resolved:* the attestation is the certification job + the
  `certification_requests` row + the `coworlds` pointer (§3); the transcript run record (the `StepResult`s, §6.1)
  is carried in the job result. Still open: the exact serialization of `StepResult.feedback` (free text vs. a
  small structured shape per `failure_reason`).
- **Authority identity.** *Resolved:* authority is the certifier **image digest** a contract version points at
  (§3). Still open: how that version → image mapping is rotated when a new certifier ships (rollout policy, a
  separate doc).
- **Hosting + hashing.** Where the transcript markdown lives and the canonical hashing of a markdown step-list
  transcript (so a degree's meaning is citable). The degree file is regenerated, not hosted (§6).
- **Grader / diagnoser harnesses.** Step 10 cannot certify grader or diagnoser until a single-container run
  harness for each exists; what those harnesses are (and the diagnoser's target-policy input) is unsettled.
- **Higher viability degrees.** What stronger-than-floor viability degrees would require, when we get there.

## See also

- [`SCHEMA_PRD.md`](SCHEMA_PRD.md) — the Coworld the certifier evaluates (the loop, the runnable families, the
  viability gate this certifier attests).
- [`src/coworld/certifier.py`](src/coworld/certifier.py) — the existing automated Executable procedure.
- [`tests/test_coworld_certifier.py`](tests/test_coworld_certifier.py) — current certifier behavior.

