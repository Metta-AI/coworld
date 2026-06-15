# Dockerfile.llm — note

**What it does.** The two-stage container build for the notsus bot *with* the LLM
voting advisor. Build stage (identical to `players/notsus/Dockerfile`): Debian
bookworm-slim, installs nimby 0.1.26 for the dpkg arch (amd64/arm64), pins Nim
2.2.4, syncs `nimby.lock`, and compiles `players/notsus/notsus.nim`
(`-d:release -d:botHeadless -d:useMalloc --opt:speed --stackTrace:on`) to a
`notsus` binary. Run stage: a fresh bookworm-slim with `ca-certificates`,
`libcurl4` (for the curly/libcurl telemetry upload path), `python3` + `pip`, and
`boto3` installed; it copies in the `notsus` binary and `advisor.py`, and runs
`/bin/notsus`.

**Why it matters to the loop.** This is the image the submitted policy actually
runs as. It is where the bot binary and the live LLM advisor are packaged
together, and where the runtime gets `boto3` + `libcurl4` so the advisor can reach
Bedrock and telemetry can upload. The advisor's model is selected at runtime by
`CREWRIFT_BEDROCK_MODEL` (defaulted in `advisor.py`); this Dockerfile provides the
boto3 + Python runtime that env relies on.

**Status: CURRENT.** The amd64-capable build for the deployed notsus policy
(arch-branching covers amd64 and arm64; league/k8s runs need the amd64 image).
Relevant memory: `libcurl4` is required because telemetry upload must use curly/
libcurl, not std/httpclient (`crewrift-nim-artifact-curl-ssl`); and `coworld
upload-policy` is broken (0.1.16), so the built image is pushed via the manual ECR
authorization-token steps (`crewrift-ecr-upload-authtoken`).
