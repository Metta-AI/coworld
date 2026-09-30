# Coworld WIT worlds

New reporter components must target [`softmax-reporter-0.6.0/world.wit`](softmax-reporter-0.6.0/world.wit). The runtime
accepts only `softmax:reporter@0.6.0`. It exposes native Anthropic Messages and OpenAI Chat Completions calls and
retains typed `tool-error` run errors and `episodes.events`'s `event-artifact` result.

Published 0.2.1–0.5.0 source files remain immutable historical contracts. The unversioned `softmax-reporter/world.wit`
is the historical 0.2.1 contract, not the current repository-supported world. Rebuild every reporter against 0.6.0,
including guests that never call an LLM: components import their declared WIT functions.

Publication requires the native API, which rejects older executable worlds. During the owner-operated maintenance
window, block new launches, stop producers and drain old work. Disable reporter workers with the existing
`reporterRunner.enabled=false` chart value, activate the native API/coordinator/sidecar, then publish 0.6 components and
update all bindings, including the platform Log reporter. Resume workers and controlled acceptance runs only after
bindings match; reopen general admission after acceptance. There is no global dispatch-pause flag: the API starts its
pending-job dispatcher. See the
[coordinated rollout](../../../../../docs/ai/onboarding/services/observatory/llm-usage.md#native-inference-deployment)
for the required external admission barrier.

Credentials stay in the trusted host. `REPORTER_OPENROUTER_MANAGEMENT_API_KEY` provisions worker-local pooled provider
keys reused across runs. Their dollar cap is the larger of `REPORTER_OPENROUTER_POOL_KEY_LIMIT_USD` (default $50) and
the run's `llm_usd` budget; run budgets reserve shared key headroom. `REPORTER_OPENROUTER_BASE_URL` and
`REPORTER_OPENROUTER_TIMEOUT_SECONDS` configure transport. Native streaming and OpenAI Responses are not part of this
world.
