# AGENTS.md — always-on heuristics (Generic software & coding-agent learnings)

Heuristics true for ANY software / coding-agent / research work, independent of games: environment & toolchain hygiene, doc-vs-code drift, testing discipline, working with a human collaborator, multi-agent orchestration. These were extracted from a Coworld player-optimization effort but apply far beyond it. For game-optimization machinery see the **loop** package; for crewrift specifics see the **crewrift** package.

_Load every session. 9 always-on heuristics. ⚠ marks session-derived, unverified items._

## Experiment discipline

#### 1. Re-run the full regression suite after every tweak, and prove a change is scoped before trusting it
`generic` · ⚠ _session-derived, unverified_ · _see related: U0356 (other tier)_

Re-run BOTH the new-feature tests and the full regression suite after EVERY hardening tweak, not once at the end, so the final reported numbers match the actual tree; green NEW tests alone never prove the old behavior still holds. Before assuming a change is local, grep the changed symbol to confirm the call-site count (e.g. confirming production had exactly ONE call site proved an edit was fully scoped). Ship regression tests that reproduce the RUNTIME failure, not the happy path, so the bug cannot silently return.
  <sub>sources: claude-code:3837ef5e-3e9c-41bc-b290-df5865581698, claude-code:bc36021d-994c-48ec-a3bc-7ec637f7464f, claude-code:c6965c58-2cb9-46fb-8b29-bad3f3e9e77f, codex:019e0140-e554-78e3-b66f-80634cc63f5d (+6)</sub>

## Agent workflow & collaboration

#### 2. Surface design-vs-code divergence and structural blast radius instead of silently complying
`generic` · ⚠ _session-derived, unverified_

Implementing a policy from a design doc tends to silently diverge (~6 ways in one phase: a kill-witness threshold flipped 1->0, reflexes in a different pipeline stage, per-reflex vs per-mode cooldowns, a centralized reflex file vs per-mode declarations, a skipped action field, a dropped flee condition). Make 'surface behavior-changing divergence before applying it' a standing AGENTS.md directive. When a human proposes removing/restructuring a mode, surface the structural blast radius (enum schema break, dispatch/reflex coupling) and ASK how to proceed rather than silently deleting and shifting the enum. When reconciling afterward, triage cosmetic stale-timestamp drift versus behavioral divergence and ASK which direction to reconcile, since behavioral divergences may be deliberate.
  <sub>sources: opencode:ses_21b475c59ffeOFBSt0jbwsGras, opencode:ses_2067f7b41ffe0wSvJ4MZlE58Q1</sub>

## Agent workflow & collaboration

#### 3. Separate reusable generator code from generated artifacts, and budget LLM-heavy stages
`generic`

In a repo that holds both reusable generator code and accumulated outputs, keep generated artifacts under an output/ tree and reusable toolkit code in the toolkit roots -- a generated helper tool under output/ is still an artifact even if it has its own source, tests, and docs -- otherwise coding agents confuse historical output with the generator they should edit. Be deliberate about which pipeline stages are LLM-heavy (multi-model doc generation was slow while the deterministic builder stage was fast); make synthesis conditional on having more than one draft, since a single selected runner can promote its draft directly and skip a meaningless single-input synthesis.
  <sub>sources: codex:019e13cd-d482-7133-a38d-c683c32a3004, codex:019e1940-5a75-7f51-b057-63f894ddb061, players_checkouts/players/tools/cogbase/README.md, players_checkouts/players/tools/cogbase/docs/artifact_pipeline.md</sub>

## Agent workflow & collaboration

#### 4. Co-locate checklist triggers with steps in the always-loaded file
`generic` · **negative result** · ⚠ _session-derived, unverified_

The hard part of checklist compliance is recognizing 'I am at checkpoint X right now,' not executing the steps once you know you're there. Co-locate the trigger condition AND the steps in the single always-loaded context file (e.g. AGENTS.md), NOT in a separate checklists/ directory referenced by a lookup table -- a separate file reintroduces the failure it tries to fix, because the agent must both recognize the checkpoint AND remember to load the file, adding a failure point at the worst moment (deep in a task, about to ship). Keep each checklist to 5-10 steps so inline stays readable even at ~800 lines total.
  <sub>sources: opencode:ses_1ff55b501ffeLso6dyHqZ2o8Bc</sub>

## Agent workflow & collaboration

#### 5. Point fresh agents at the right entry docs and ephemeral working memory via AGENTS.md
`generic`

A per-project AGENTS.md should point a fresh agent up front at the canonical operational docs and a sibling lessons file, instructing it to follow the upstream walkthrough with local fixes applied inline. It can require reading a per-project notes file (e.g. PROJECT_NOTES.md) on first invocation each session, treated as ephemeral cross-session working memory (short-term hints) rather than permanent documentation -- expect it to sometimes be an empty scratch-pad template. A machine-detectable signal in project state can mark onboarding as done (resume work) versus absent (start guided onboarding). Treat code under a testbed/ directory as live and unstable -- interfaces change without notice and behavior may be wrong -- so automation and agents must not depend on it and should expect breakage until it is promoted into the main package.
  <sub>sources: metta/agent-plugins/kitchensink/skills/ks.cross-agent-skill-layout/SKI, bitworld/among_them/players/evidencebot_v3/AGENTS.md, player_labs/README.md, player_labs/AGENTS.md (+1)</sub>

## Agent workflow & collaboration

#### 6. Propose-and-pause: do not auto-chain into unrequested gameplay changes
`generic`

Follow propose-and-pause: when a thread of work finishes, propose the next step and pause rather than auto-chaining into unrequested work, especially behavior changes. When a task is fenced as operations-only, do not drift into behavior changes. Given a vague 'improve X' prompt, refresh the project docs (DESIGN.md/TODO.md) first and pick the highest-impact self-contained backlog item rather than committing to the first idea -- in one session this redirected from a marginal tweak to a more self-contained, higher-impact fix.
  <sub>sources: codex:019e8afb-efcd-7ca0-820f-0320501ef2fa, player_labs/AGENTS.md, codex:019e191b-e5d6-7c43-b54c-8283e76cd26f</sub>

## Environment & toolchain

#### 7. Always run through the project's pinned interpreter and package manager, never system python/pip
`generic`

In uv/Python projects a bare `python`/`pip` is often missing or lacks deps; run every check via `.venv/bin/python`, `uv run python`, or `uv run <cli>` with the documented `PYTHONPATH` set, including throwaway smoke/compile commands (`.venv/bin/python -m py_compile ...`). A `python -c` 'command not found' is a PATH problem, not a code failure; rerun with the venv first. Modern Homebrew/system Python (PEP 668) blocks `pip install` with 'externally managed environment' -- do not use `--break-system-packages`; a per-project `uv venv` is the reproducible path. Create that venv at the project root, never installing into a shared/global venv (which it can downgrade/pollute). A missing package in the project venv is a fix (install it INTO that venv), not a blocker. When `pip show` fails because pip is absent, read version/metadata via importlib.metadata.
  <sub>sources: alpha_cog/AGENTS.md, claude-code:fa645b7b-4fa0-4b55-992e-b273ee703391, codex:019dfef8-dc40-7273-b85a-04aa3a51ff07, codex:019e00a3-98da-75b3-89f8-ed86e1fc3b99 (+8)</sub>

## Environment & toolchain

#### 8. metta commits/pushes MUST run inside `nix develop`; check the filesystem before deciding a tool is 'not installed'
`generic` · ⚠ _session-derived, unverified_

Do not work around a toolchain guard that requires a sanctioned environment (e.g. metta commits/pushes must run inside `nix develop` because the pre-commit/pre-push hooks require the Nix flake -- never bypass with an env override or `--no-verify`; install and enter the sanctioned env). Before concluding a tool 'isn't installed', check the filesystem and known install locations (e.g. /nix, ~/.nix-profile, /opt/homebrew/bin, /usr/local/bin, /run/current-system/sw/bin), not just `command -v`/PATH: an agent's Bash tool runs a non-login shell sourcing a snapshot, not login rc files, so a tool added to PATH by a profile.d script shows as missing. To use an installed-but-unsourced tool, source its profile script then run the guarded operation inside the sanctioned env.
  <sub>sources: claude-code:8e1dadfd-ab6e-4cec-8910-806828a5e82f, claude-code:a30ff353-3fc5-4f33-92cb-30810f530920</sub>

## Environment & toolchain

#### 9. Do not use `sed` for edits in this agent environment - it triggers an ungrantable permission prompt
`generic` · ⚠ _session-derived, unverified_

Do not use `sed` for text edits in this Claude/Codex agent environment: it cannot be whitelisted, so every invocation triggers an ungrantable permission prompt that stalls autonomous loops. Use Read/Grep/Edit or a small Python script instead.
  <sub>sources: claude-code:425dc11e-1c8d-4d12-bf44-adf01b6fa796, claude-code:e049dbf8-9702-41e5-8ac5-830cde8a27ad, codex:019de5a5-fadf-70b3-8773-2072cabae94c</sub>
