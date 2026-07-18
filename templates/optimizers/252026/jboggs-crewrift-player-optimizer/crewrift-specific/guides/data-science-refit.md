# Data-science refit (outer loop) — guide (crewrift tier)

Reference notes, design rationale, and negative results (2).

#### 1. Prevent leakage when training on game replays: group-CV, no look-ahead, visibility-clip, raw counts
`crewrift`

Rows within one game are correlated (cumulative observer-suspect snapshots grow monotonically across meetings), so use game-grouped cross-validation (sklearn GroupKFold, group=game; split by game never by row) or correlated rows leak into train and test and inflate AUC. Build per-(observer,suspect,meeting) rows where each row is one belief state: accumulate positional evidence cumulatively from tick 0 to the decision tick (never reset), but draw public/meeting evidence only from PRIOR meetings so a row never contains the outcome of the decision it predicts. Visibility-clip every positional cue using the replay expander's exact per-(observer,target) rendered-view intervals (never a modelled approximation) so offline features equal what a player in that seat could have seen; use edge-triggered detection for discrete events (count the transition INTO a vent, not every tick inside); include an exposure feature (observed_samples) to distinguish 'no evidence because innocent' from 'never observed'; and emit RAW counts/durations, deferring all binning to fit time.
  <sub>sources: personal_labs/crewrift_lab/suspicion_lab/tools/features.py, personal_labs/crewrift_lab/suspicion_lab/tools/build_dataset.py, personal_labs/crewrift_lab/crewrift/crewborg/docs/designs/suspicion-le, personal_labs/crewrift_lab/crewrift/crewborg/docs/designs/suspicion.md</sub>

#### 2. Emit per-slot survival and summary metrics: each is free anomaly coverage and fills the missing fitness signal
`crewrift`

Crewrift fitness scoring has no survival term -- survivalRate is hard-coded null because the cross-game results contract gives no alive/dead signal -- so emitting per-slot death tick and survival_ticks in the event log fills the single most-wanted missing fitness signal. Precompute debugging signals as summary.* rows at the final tick: survival_ticks = death_tick - gameStartTick (or maxTick - start if never killed), time_to_first_task, vote_accuracy (fraction of a crew slot's votes targeting a real imposter, -1 for imposters), votes_received. Each new summary metric is also free anomaly coverage: the optimizer's detector z-scores and IQR-fences every numeric key in each episode's flat scores map, so a new per-episode numeric summary metric automatically becomes a new anomaly dimension at zero extra parsing cost.
  <sub>sources: optimizers/docs/events-parquet-spec.md</sub>
