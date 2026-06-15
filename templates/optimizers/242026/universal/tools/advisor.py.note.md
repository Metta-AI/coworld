# advisor.py — note

**What it does.** The live LLM voting advisor for the notsus bot. It reads a
compact meeting snapshot as JSON on stdin and prints one line of JSON
`{"vote": "<color or skip>", "chat": "<short line or empty>"}`. It calls a Bedrock
Claude model (default `us.anthropic.claude-opus-4-7`, overridable via
`CREWRIFT_BEDROCK_MODEL`) with a role-specific system prompt: as crew, reason from
body proximity / last-seen rooms / unseen players / corroborated accusations and
vote the most likely imposter (only skip with no lead); as imposter, blend in —
bandwagon a non-teammate, deflect when accused, never reveal the role, never vote a
teammate. On any failure it exits non-zero printing nothing usable, so the Nim bot
falls back to its scripted heuristic floor (the game must still play if Bedrock or
credentials are unavailable).

**Key entry points.** `main()` — parses the snapshot, builds the boto3
`bedrock-runtime` client (bounded retries + tight read/connect timeouts to stay
within the ~6s vote deadline, `LLMVoteDeadlineTicks=150 @ 24fps`), invokes the
model, extracts the JSON object, and validates the vote against the offered
`options` (invalid → skip). The bare `try/except` at module bottom is the
deliberate "any failure → heuristic fallback" contract, not silent error-hiding.

**Why it matters to the loop.** This is the in-bot deduction lever on the vote
path — the component being tuned to convert meetings into imposter ejections.
(Per memory, the dead/abstaining advisor was a measured root cause of the
vote-conversion defect, so this file is squarely a policy-improvement surface.)

**Status: CURRENT.** The live advisor invoked by the deployed notsus bot;
shipped into the image by `Dockerfile.llm` (`COPY players/notsus/advisor.py
/app/advisor.py`) and parametrized by the same Bedrock model env that Dockerfile
sets.
