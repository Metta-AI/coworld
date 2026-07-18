# A/B methodology & attribution — guide (crewrift tier)

Reference notes, design rationale, and negative results (3).

#### 1. Compiled-binary policies ignore params; param-only versions produce identical episodes -- edit source
`crewrift` · **negative result**

For compiled-binary Coworld policies whose behavior is baked at build time (e.g. crewrift's Nim 'notsus', which ignores params), generating param-only versions produces identical episodes because they reuse the same cached image. Make distinct SOURCE edits instead, each committed as a source-backed version with its own rebuilt image.
  <sub>sources: optimizers/docs/optimizer-primitives.md</sub>

#### 2. Tune scripted policies by runtime param injection against the Crewrift results schema
`crewrift`

For a parameter-tuned scripted Among-Them/Crewrift policy, inject params into the scripted baseline at runtime with no LLM calls in the policy, reduce episode results to a single fitness number (winRate), and start from a baseline that already wins sometimes. A small bounded param set suffices: voteThreshold (0.3-0.9), suspicionDecay (0.5-0.99), taskPriority (0.0-1.0, tasks vs following suspects), killCooldownAggression (0.0-1.0), reportTruthfulness (0.0-1.0, imposter bluffing honesty). The Crewrift results schema is the score target -- per-slot arrays scores (required scalar), win (bool), tasks, kills, imposter/crew (1/0), vote_players, vote_skip, vote_timeout, connect_timeout, disconnect_timeout, all length 1-16; design score functions over these fields.
  <sub>sources: optimizers/docs/spec-simple-optimizer.md, coworlds/coworld-crewrift/coworld_manifest.json</sub>

#### 3. Evaluate a fitted suspicion model at decision level, make the belief layer falsifiable, and gate refits as a pure ordered pipeline
`crewrift`

Evaluate a fitted suspicion/voting model with a DECISION-level simulator, not AUC alone: replay held-out meetings through the posterior plus a candidate vote policy and report imposter-hit rate, crew-mis-vote rate, and would-have-skipped rate, because the thresholds chosen are probabilities and outcomes depend on actual decisions; ship the learned vote model only if its net parity score clearly beats the always-skip baseline (0 net by definition). Make the belief layer falsifiable: when a tracked agent is re-acquired, log predicted grid cell (prior-tick argmax) vs actual plus distance error and disc radius, then offline measure top-1/top-k accuracy and calibration against replays as the fitness signal for priors and grid size. Keep the fitter pure -- write quality metrics (cv_auc, games) into the weights JSON but let the orchestrator enforce floors so thresholds live in one place; structure the unattended champion-refit as ordered gates where ANY failure aborts leaving the champion untouched (scrape+expand data, rebuild+refit, then gate on CV AUC >= 0.70 and corpus >= 500 games, full test suite, local smoke run); only a fully-passing candidate gets vendored, imaged, uploaded, and submitted.
  <sub>sources: personal_labs/crewrift_lab/crewrift/crewborg/docs/designs/suspicion-le, personal_labs/crewrift_lab/suspicion_lab/tools/eval.py, personal_labs/crewrift_lab/crewrift/crewborg/docs/designs/agent-tracki, personal_labs/crewrift_lab/suspicion_lab/tools/fit.py (+1)</sub>
