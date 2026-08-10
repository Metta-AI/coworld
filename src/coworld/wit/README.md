# Coworld WIT worlds

Reporter worlds are immutable once published and accepted side by side:

- [`softmax-reporter/world.wit`](softmax-reporter/world.wit) is
  `softmax:reporter@0.2.1`, the current legacy world with Bedrock-shaped LLM
  calls.
- [`softmax-reporter-0.3.0/world.wit`](softmax-reporter-0.3.0/world.wit) adds
  synchronous native Anthropic Messages and OpenAI Chat Completions calls.
- [`softmax-reporter-0.4.0/world.wit`](softmax-reporter-0.4.0/world.wit) changes
  the exported `run` error from `string` to the shared `tool-error` variant.

New reporter components should target 0.4.0. The host links native LLM imports
only for components that declare 0.3.0 or 0.4.0. Native streaming and OpenAI
Responses are not part of these worlds.

Reporter Bureau enables the native functions when its deployment supplies
`REPORTER_OPENROUTER_API_KEY`. `REPORTER_OPENROUTER_BASE_URL` and
`REPORTER_OPENROUTER_TIMEOUT_SECONDS` configure the shared synchronous
transport. These values stay in the trusted host and are never exposed to the
reporter component. Run-scoped limited-key brokerage is a separate rollout
requirement; this world does not define credential delivery.
