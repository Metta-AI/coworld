# Bedrock For Coworld Players

**Status:** live

Players that call an LLM can use AWS Bedrock in hosted tournaments **without shipping their own model credentials**. The
platform runs a per-pod proxy (the "Bedrock sidecar") that holds the real identity and signs your calls for you.

> ## ⚠️ THE ONE RULE — send Bedrock calls to `AWS_ENDPOINT_URL_BEDROCK_RUNTIME`
>
> In a hosted episode your player pod is given the env var **`AWS_ENDPOINT_URL_BEDROCK_RUNTIME`** (e.g.
> `http://127.0.0.1:9100`). **Every Bedrock call must go to that endpoint.** If you send to the real AWS host
> (`https://bedrock-runtime.<region>.amazonaws.com`) instead, you bypass the sidecar, your call carries the
> **placeholder credentials** the platform injected, and AWS rejects it with **HTTP 403**. The episode then silently
> falls back to a non-LLM baseline (no useful model calls, and no error visible in the score).
>
> **If you use a standard SDK, you get this for free** — boto3, `AnthropicBedrock`, the AWS SDK for JS, and
> `@cogweb/llm` all read `AWS_ENDPOINT_URL_BEDROCK_RUNTIME` automatically. **Only hand-rolled HTTP must read the env var
> itself.** Never hardcode the host or the port.
>
> Two more rules that follow from the same proxy:
> - **Use `InvokeModel`, not `Converse`.** The runner identity is granted `bedrock:InvokeModel` only —
>   `bedrock:Converse` returns `AccessDenied`. (boto3 `invoke_model`, `AnthropicBedrock`, and `@cogweb/llm` use
>   InvokeModel; only raw `…/converse` calls hit this.)
> - **Don't supply real AWS credentials and don't worry about signing.** The sidecar strips whatever auth you send and
>   re-signs with the real runner identity. The `bedrock-sidecar` placeholder creds in your env are deliberately fake.

## How to make the call

### Detecting that you're behind the sidecar

The presence of **`AWS_ENDPOINT_URL_BEDROCK_RUNTIME`** is the signal that hosted Bedrock is available via the sidecar.
Gate on that env var — do **not** gate solely on `USE_BEDROCK`, which the sidecar path does not set.

The platform injects this env into a hosted player pod when the coworld is Bedrock-enabled and your policy was uploaded
with `--use-bedrock`:

| Env var | Value in a hosted, sidecar-backed pod | What you do with it |
| --- | --- | --- |
| `AWS_ENDPOINT_URL_BEDROCK_RUNTIME` | the sidecar, e.g. `http://127.0.0.1:9100` | **Send all Bedrock calls here.** Read it; never hardcode. |
| `AWS_REGION` / `AWS_DEFAULT_REGION` | the Bedrock region | The SigV4 region (the SDK reads it automatically). |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | `bedrock-sidecar` (placeholder) | Leave as-is. The sidecar re-signs; these never reach AWS. |
| `AWS_BEARER_TOKEN_BEDROCK` | `bedrock-sidecar` (placeholder) | Same — placeholder, stripped by the sidecar. |
| `BEDROCK_MODEL` | the model id from `--bedrock-model` | **Read your model from this**; do not hardcode a model id. |

### Standard SDKs — these route through the sidecar automatically

```python
# Python — Anthropic SDK (Messages API over Bedrock InvokeModel). Honors AWS_ENDPOINT_URL_BEDROCK_RUNTIME.
import os
from anthropic import AnthropicBedrock
client = AnthropicBedrock()  # picks up region + the sidecar endpoint from env
resp = client.messages.create(
    model=os.environ["BEDROCK_MODEL"],
    max_tokens=512,
    messages=[{"role": "user", "content": "..."}],
)
```

```python
# Python — boto3. The endpoint comes from AWS_ENDPOINT_URL_BEDROCK_RUNTIME automatically.
import boto3, json, os
rt = boto3.client("bedrock-runtime")  # endpoint auto-resolved from the env var
out = rt.invoke_model(
    modelId=os.environ["BEDROCK_MODEL"],
    body=json.dumps({"anthropic_version": "bedrock-2023-05-31", "max_tokens": 512,
                     "messages": [{"role": "user", "content": "..."}]}),
)
```

```js
// JS/TS — @cogweb/llm handles the endpoint + InvokeModel for you. Prefer this in cogweb players.
// (Under the hood: @aws-sdk/client-bedrock-runtime InvokeModel pointed at AWS_ENDPOINT_URL_BEDROCK_RUNTIME.)
```

### Hand-rolled HTTP (the only path that must read the env var itself)

Build the URL from the endpoint env var and call **`/invoke`** (InvokeModel) with the Anthropic Messages body. No
`Authorization` header is needed — the sidecar adds the real one:

```bash
curl -sS -X POST \
  "$AWS_ENDPOINT_URL_BEDROCK_RUNTIME/model/$BEDROCK_MODEL/invoke" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -d '{"anthropic_version":"bedrock-2023-05-31","max_tokens":512,
       "messages":[{"role":"user","content":"ping"}]}'
```

In code: `base = AWS_ENDPOINT_URL_BEDROCK_RUNTIME or "https://bedrock-runtime.$AWS_REGION.amazonaws.com"`, then
`POST {base}/model/{BEDROCK_MODEL}/invoke`. Do **not** set `requestMetadata` — the sidecar replaces it with the trusted
attribution; anything you put there is overwritten.

### Verify it's reachable

```bash
echo "$AWS_ENDPOINT_URL_BEDROCK_RUNTIME"             # expect http://127.0.0.1:<port>; empty => no hosted Bedrock
curl -sS "$AWS_ENDPOINT_URL_BEDROCK_RUNTIME/healthz" # expect: ok
```

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `HTTP 403` (e.g. `UnrecognizedClientException`, invalid token/signature) on every call | You're hitting the **real AWS host** with the placeholder creds — bypassing the sidecar | Send to `$AWS_ENDPOINT_URL_BEDROCK_RUNTIME`. Log the exact URL you POST to. |
| `AccessDenied` for `bedrock:Converse` | You used the **Converse** API | Switch to **InvokeModel** (`/model/{id}/invoke`, Anthropic Messages body). |
| `AWS_ENDPOINT_URL_BEDROCK_RUNTIME` is empty/unset | The sidecar isn't attached — coworld not Bedrock-enabled, policy not uploaded with `--use-bedrock`, or you're running locally | Locally, use your own AWS creds (below). For hosted, fix the upload (`--use-bedrock`) and confirm the coworld is enabled. |
| 0 completed episodes / silent non-LLM baseline in hosted rounds | A failing model call is being swallowed and you fall back | Log the **response body** and the **endpoint URL** before anything else; it's almost always the 403/route issue above. |

When debugging, **log the response body, not just the status code** — the Bedrock error body names the exact failure
(route vs. action vs. model). A bot that logs only `HTTP 403` hides which one it is.

## Enable Bedrock at upload time

Bedrock is opt-in per submitted policy, set by upload flags — it is not inferred from your image:

```bash
uv run coworld upload-policy my-player:latest --name "$USER-my-player" \
  --run python --run -m --run my_player.module \
  --use-bedrock \
  --bedrock-model us.anthropic.claude-haiku-4-5-20251001-v1:0
```

- `--use-bedrock` gives the hosted player Bedrock access (via the sidecar) without its own API key.
- `--bedrock-model MODEL` sets `BEDROCK_MODEL`. Your player must read its model from `BEDROCK_MODEL` — do not hardcode a
  model ID or read a different variable name.

Local `run-episode --use-bedrock` / `play --use-bedrock` uses **your own** AWS credentials (resolved via the AWS CLI /
`--aws-profile`), so it proves your code can call Bedrock but **not** that the upload is correct — locally there is no
sidecar, so the call goes straight to AWS with your real creds. A Bedrock player can pass local certification at full
score and still be disqualified in its first hosted rounds if it was uploaded without `--use-bedrock`, reads its model
from the wrong variable, or hardcodes the AWS host instead of `AWS_ENDPOINT_URL_BEDROCK_RUNTIME`; those episodes produce
no gameplay (0 completed episodes, no replay). Check the upload flags, `BEDROCK_MODEL`, and the endpoint first.

## Track your spend (and the league's spend limit)

Leagues can set a per-episode LLM spend limit for each player pod. The sidecar meters every call's token usage against
public list prices (an estimate, not billing data) and, once the running total reaches the limit, rejects further calls
for the rest of the episode with a standard Bedrock `ThrottlingException` (`HTTP 429`) — the exact failure mode the
["Be robust to throttling"](#be-robust-to-throttling) section below already requires you to handle. A player that
handles throttling correctly needs **zero new code** for spend limits; there is no Softmax-specific exception type.

You don't have to wait for the 429 — the sidecar tells you where you stand:

- **Response headers** on every proxied Bedrock call:
  - `X-Coworld-Spend-Usd` — the pod's running estimated spend after that call (for streaming calls: before it, since
    headers are sent ahead of the body).
  - `X-Coworld-Spend-Limit-Usd` — the league's limit; absent when the league has no limit.
- **`GET $AWS_ENDPOINT_URL_BEDROCK_RUNTIME/spend`** — current totals as JSON:

```bash
curl -sS "$AWS_ENDPOINT_URL_BEDROCK_RUNTIME/spend"
# {"spend_usd": 0.42, "spend_limit_usd": 1.5, "remaining_usd": 1.08}
# spend_limit_usd / remaining_usd are null when the league has no limit.
```

With boto3, the headers are on `response["ResponseMetadata"]["HTTPHeaders"]["x-coworld-spend-usd"]`. A budget-aware
player can, for example, switch to a cheaper model or shorter prompts as `remaining_usd` shrinks.

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
