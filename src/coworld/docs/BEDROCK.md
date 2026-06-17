# Bedrock For Coworld Players

**Status:** live

Players that call an LLM can use AWS Bedrock in hosted tournaments instead of shipping their own model credentials. Two
things catch player authors out.

## Enable Bedrock at upload time

Bedrock is opt-in per submitted policy, set by upload flags — it is not inferred from your image:

```bash
uv run coworld upload-policy my-player:latest --name "$USER-my-player" \
  --run python --run -m --run my_player.module \
  --use-bedrock \
  --bedrock-model us.anthropic.claude-haiku-4-5-20251001-v1:0
```

- `--use-bedrock` gives the hosted player Bedrock access without its own API key.
- `--bedrock-model MODEL` sets `BEDROCK_MODEL`. Your player must read its model from `BEDROCK_MODEL` — do not hardcode a
  model ID or read a different variable name.

Local `run-episode --use-bedrock` / `play --use-bedrock` uses your own AWS credentials, so it proves your code can call
Bedrock but not that the upload is correct. A Bedrock player can pass local certification at full score and still be
disqualified in its first hosted rounds if it was uploaded without `--use-bedrock` or reads its model from the wrong
variable; those episodes produce no gameplay (0 completed episodes, no replay). Check the upload flags and `BEDROCK_MODEL`
first.

## Be robust to throttling

Hosted Bedrock capacity is shared across players and can run out under load; calls then fail with a throttling error
("Too many tokens per day"). If your player blocks on a model call, the episode runs to its timeout — and a timed-out
episode is scored as a loss no matter how well the policy plays.

Assume capacity can run out and keep the player playing:

- Bound each model call (timeout plus a retry cap) so one slow call cannot consume the episode.
- On a throttle or error, fall back to a valid default move instead of waiting.
- Always submit a valid action before the episode timeout.

## See Also

- [Player role — secrets, Bedrock, and LLM credentials](roles/PLAYER.md#secrets-bedrock-and-llm-credentials)
- [COOKBOOK.md — Upload And Submit A Player](../../../COOKBOOK.md#upload-and-submit-a-player)
