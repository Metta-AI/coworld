# advisor.py — native migration note

The external notsus advisor reads a meeting snapshot from stdin and returns one JSON line:
`{"vote": "<offered color or skip>", "chat": "<short line or empty>"}`. It must validate the offered options and finish
before the game's vote deadline. The Nim core retains its scripted fallback when the advisor fails.

Rebuild the external advisor for native Anthropic Messages or OpenAI Chat. Hosted calls use `COWORLD_LLM_ENDPOINT`
and placeholder SDK credentials; local calls use a configured native endpoint or `OPENROUTER_API_KEY`.
Read a canonical model from `COWORLD_LLM_MODEL`, such as `anthropic/claude-haiku-4.5`, when allowed by platform policy.
Retain the template's 1,800 quota-weighted-token episode budget (`input + cache-write + 5 × output`).

This note specifies the required migration. It does not claim the external advisor source or a published image has
already migrated. Verify the stdin/stdout contract and a real hosted inference call after rebuilding and republishing.
