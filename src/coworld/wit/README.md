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
`REPORTER_OPENROUTER_MANAGEMENT_API_KEY`. For each native-capable run, the
trusted worker mints an inference key whose provider limit equals the run's
`llm_usd` budget. `REPORTER_OPENROUTER_BASE_URL` and
`REPORTER_OPENROUTER_TIMEOUT_SECONDS` configure the transport. Credentials stay
in the trusted host and are never exposed to the reporter component; this world
does not define credential delivery.
