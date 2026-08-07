# Coworld WIT worlds

Reporter worlds are immutable once published and accepted side by side:

- [`softmax-reporter/world.wit`](softmax-reporter/world.wit) is
  `softmax:reporter@0.2.1`, the current legacy world with Bedrock-shaped LLM
  calls.
- [`softmax-reporter-0.3.0/world.wit`](softmax-reporter-0.3.0/world.wit) adds
  synchronous native Anthropic Messages and OpenAI Chat Completions calls.

New reporter components that need native LLM calls should target 0.3.0. The
host links those imports only for a component that declares that world. Native
streaming and OpenAI Responses are not part of this world.

Reporter Bureau enables the native functions only when its deployment supplies
both `REPORTER_OPENROUTER_API_KEY` and a materialized
`REPORTER_OPENROUTER_MODEL_ALLOWLIST`. An absent allowlist prevents the Reporter
worker from starting or claiming runs; an empty list intentionally denies every
model. `REPORTER_OPENROUTER_BASE_URL` and
`REPORTER_OPENROUTER_TIMEOUT_SECONDS` configure the shared synchronous
transport. These values stay in the trusted host and are never exposed to the
reporter component. Run-scoped limited-key brokerage is a separate rollout
requirement; this world does not define credential delivery.
