# Training trajectories

Games write private decision evidence to `COGAME_SAVE_TRAJECTORY_URI`. This artifact is separate from public replays.
Local episode runs use `trajectory.jsonl` in the episode workspace. Hosted artifact access is restricted to team users.

The game engine records its seat-private observation, every model attempt, rejected proposals, and the action it
actually executed. The selected accepted proposal must equal that executed action. Fallbacks retain their controller
origin and are excluded from model imitation labels.

Each attempt preserves the exact prompt, native request, raw provider response, parsed action, model, decoding settings,
and response-header `X-Softmax-Llm-Call-Id`. Client-generated identifiers cannot substitute for the platform call ID.
Each completed episode includes its terminal outcome, seed family, game version, and immutable source revision. Both
event JSONL and complete-episode JSONL envelopes are supported. Every line is validated against typed models.

The trajectory models and `read_trajectory_jsonl` preserve historical event and complete-episode formats.
`export_complete_episodes` converts event streams without publishing incomplete tails; conversion alone does not
authorize training labels. Keep original private artifacts for the application trainer's authenticated export.

The trainer must verify source and participant authority, fetch native receipts, select learner or reviewed teacher
labels, and split whole seed families. A local capture or player-supplied call ID cannot establish hosted authority.
Rejected attempts remain evidence, not accepted-action labels. Reinforcement learning requires identities and token
likelihoods from the sampler that drew the actions; retokenizing responses cannot establish them.

To qualify a release, run the ordinary hosted player with a saved and reloaded learner checkpoint. Verify prompts, legal
actions, phases, deadlines, and decoding settings against collection and evaluation. Report complete held-out outcomes,
invalid actions, fallbacks, latency, and model cost. Pin and read back the released game, player, and images.
