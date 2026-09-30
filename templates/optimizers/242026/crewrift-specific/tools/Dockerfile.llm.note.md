# Dockerfile.llm — native migration note

The external notsus image packages the compiled Nim player, Python voting advisor, and telemetry runtime together.
Preserve the existing native build and `libcurl4` requirement for telemetry uploads. Rebuild the advisor layer with its
native SDK dependency; runtime AWS identity is not an inference credential.

The native advisor must consume `COWORLD_LLM_ENDPOINT`, `COWORLD_LLM_ENABLED`, and a canonical `COWORLD_LLM_MODEL`.
Keep provider keys out of the hosted image. Opt into hosted inference when uploading the rebuilt policy with `--use-llm`.
Retain the advisor's bounded vote deadline and episode token budget.

This is a required migration for external source and published images, not evidence that either has already changed.
Verify the target CPU architecture, offline fallback, and a real native call before comparing league performance.
