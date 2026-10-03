# Hosted LLM Calls For Coworld Players

For runtime selection, see [Choose a Player Runtime](PLAYER_RUNTIMES.md). The player-pod upload flags below apply to
`platform-hosted` players. In `game-hosted` mode, the game uses its own sidecar and supplies `X-Coworld-Player-Slot: N`
on every request for seat `N`. File policies have no environment, secrets, or player sidecar; see
[the game contract](roles/GAME.md#hosted-llm-access).

Players that call an LLM can do so in hosted tournaments **without shipping their own model credentials**. The platform
runs a per-pod proxy (the "LLM sidecar") that holds the real provider key, forwards your calls to
[OpenRouter](https://openrouter.ai), and meters spend against league and experience-request limits.

> ## ⚠️ THE ONE RULE — send every model call to `COWORLD_LLM_ENDPOINT`
>
> In a hosted episode your player pod is given the env var **`COWORLD_LLM_ENDPOINT`** (e.g. `http://127.0.0.1:9100`).
> The value is the sidecar's base URL. **Every model call must go to that endpoint.** The pod has no provider
> credentials of its own, so a client that calls `api.anthropic.com`, `api.openai.com`, `openrouter.ai`, or any AWS host
> directly fails with an authentication error. Whether the player then falls back or breaks depends on the player
> implementation.
>
> **Don't supply a real API key and don't worry about auth.** The sidecar ignores whatever auth header you send and
> attaches the real key itself. Standard SDKs need a non-empty key to construct a client, so pass any placeholder. Never
> hardcode the host or the port.

## Operator-hosted models

When enabled by the platform operator, `self-hosted/...` models use the same sidecar endpoint through
`/v1/chat/completions`. Use the exact model name supplied by the operator. Unknown private names return an error; they
never fall back to a public provider. Anthropic Messages and System One are not supported for these models. Token counts
are recorded normally. Provider-billed spend is zero for these calls; separately billed GPU infrastructure is not
included in that meter. Request limits and model allowlists still apply.

## How to make the call

### Detecting that you're behind the sidecar

The presence of **`COWORLD_LLM_ENDPOINT`** is the signal that the hosted sidecar is available. Gate on that env var, not
on `COWORLD_LLM_ENABLED`, which is the stored enablement flag rather than a runtime signal.

The platform adds the sidecar and injects this environment into a hosted player pod when its policy was uploaded with
`--use-llm`:

| Env var                | Value in a hosted, sidecar-backed pod          | What you do with it                                              |
| ---------------------- | ---------------------------------------------- | ---------------------------------------------------------------- |
| `COWORLD_LLM_ENDPOINT` | the sidecar, e.g. `http://127.0.0.1:9100`      | **Send all model calls here.** Read it; never hardcode.          |
| `COWORLD_LLM_MODEL`    | the model id from `--llm-model`, when provided | Read your model from this when your policy uses the upload flag. |

### Which models you can name

Name models by their canonical OpenRouter slug, for example `anthropic/claude-haiku-4.5`, `anthropic/claude-sonnet-4.6`,
or `amazon/nova-micro-v1`. Short aliases and provider-specific inference IDs are rejected; the gateway does not
translate them. Models outside the league's allowed set are rejected before any call leaves the pod. A canonical slug
the provider does not serve fails with the provider's error, so verify the model exists before relying on it.

### The endpoints the sidecar serves

| Path                        | Wire format                                                            |
| --------------------------- | ---------------------------------------------------------------------- |
| `POST /v1/messages`         | Anthropic Messages API. Use it with the Anthropic SDK or plain HTTP.   |
| `POST /v1/chat/completions` | OpenAI Chat Completions API. Use it with the OpenAI SDK or plain HTTP. |
| `POST /v1/systemone`        | OpenRouter System One API (Jev). Plain HTTP only; see below.           |
| `GET /spend`                | The pod's running spend and limits as JSON (see below).                |
| `GET /healthz/core-v1`      | Liveness probe; returns `ok`.                                          |

Streaming is not supported: a request with `stream: true` is rejected with HTTP 400. Bound your `max_tokens` instead.

### Standard SDKs

```python
# Python — Anthropic SDK. base_url is the sidecar; the api_key is a placeholder the sidecar ignores.
import os
from anthropic import Anthropic

client = Anthropic(base_url=os.environ["COWORLD_LLM_ENDPOINT"], api_key="sidecar")
resp = client.messages.create(
    model=os.environ["COWORLD_LLM_MODEL"],
    max_tokens=512,
    messages=[{"role": "user", "content": "..."}],
)
```

```python
# Python — OpenAI SDK. The SDK appends /chat/completions, so the base URL includes /v1.
import os
from openai import OpenAI

client = OpenAI(base_url=f"{os.environ['COWORLD_LLM_ENDPOINT']}/v1", api_key="sidecar")
resp = client.chat.completions.create(
    model=os.environ["COWORLD_LLM_MODEL"],
    max_tokens=512,
    messages=[{"role": "user", "content": "..."}],
)
```

The same pattern works for the JavaScript SDKs with any placeholder `apiKey`: the Anthropic SDK takes the env var
unchanged as `baseURL`; the OpenAI SDK needs `${endpoint}/v1`, as in the Python example.

### Hand-rolled HTTP

Hand-rolled clients must build the URL from the endpoint environment variable. No auth header is needed:

```bash
curl -sS -X POST "$COWORLD_LLM_ENDPOINT/v1/messages" \
  -H "Content-Type: application/json" \
  -H "anthropic-version: 2023-06-01" \
  -d "{\"model\":\"$COWORLD_LLM_MODEL\",\"max_tokens\":512,
       \"messages\":[{\"role\":\"user\",\"content\":\"ping\"}]}"
```

Routing fields such as `provider`, `models`, `route`, `plugins`, and `metadata` are owned by the platform; the sidecar
replaces any you send.

### System One models (Jev)

TypeSafe's System One model Jev is not a chat model: you send it a JSON `state` and a set of typed `questions`, and it
answers each question. The sidecar serves OpenRouter's System One wire format at `POST /v1/systemone` under the same
policy as the chat endpoints: the model allowlist, the spend limit, a request ceiling, and the platform-owned routing
fields all apply, and a game container attributes a call to a seat with `X-Coworld-Player-Slot`. System One calls count
against their own request bucket, at four times the chat ceiling (120 per minute per slot by default); see
[Stay under the request ceiling](#stay-under-the-request-ceiling).

Name the pinned slug `typesafe/jev-1.13`. The moving alias `~typesafe/jev-latest` is not a canonical slug, so the
sidecar rejects it with HTTP 403. The league must also allow the model.

The request is a JSON object with `model`, a required `state` value, and `questions` (a non-empty object keyed by your
own question ids). The sidecar forwards the state unchanged, including `null`; the provider validates its content. Each
question has a `type`, optional `instructions`, and `criteria` whose shape depends on the type:

| `type`   | Answers                                   | `criteria`                                                              |
| -------- | ----------------------------------------- | ----------------------------------------------------------------------- |
| `noul`   | the probability that the answer is yes    | optional: an object with `true` and/or `false` descriptions, or null    |
| `choice` | one option, with a probability per option | required: a non-empty object mapping each option label to a description |
| `score`  | a position along ordered levels           | required: a non-empty array of level descriptions, lowest first         |

The sidecar itself rejects, with HTTP 400 before any call leaves the pod, a request without `state` or with missing or
empty `questions`. It does not validate question shapes: a `criteria` of the wrong shape (an object for a `score`, a
string for a `noul`) is forwarded and comes back as the provider's HTTP 400, which names the offending path.

```bash
curl -sS -X POST "$COWORLD_LLM_ENDPOINT/v1/systemone" \
  -H "Content-Type: application/json" \
  -d '{"model": "typesafe/jev-1.13",
       "state": {"tick": 41, "paint": {"red": 12, "blue": 9}},
       "questions": {"push": {"type": "noul",
                              "instructions": "Should red push the center?",
                              "criteria": {"true": "red leads on paint and holds the nearer hearts",
                                           "false": "red is behind or outnumbered near the center"}}}}'
# {"id": "gen-dec-...", "model": "typesafe/jev-1.13-20260917", "provider": "TypeSafe",
#  "answers": {"push": {"type": "noul", "noul": 0.87}},
#  "usage": {"input_tokens": 339, "output_tokens": 20, "cost": 0.000014238}}
```

`answers` is keyed by the same ids as `questions`. Errors use OpenRouter's System One shape whether the sidecar or the
provider raised them: `{"error": {"message": "...", "code": 400}}`, with `code` equal to the HTTP status. The sidecar's
own statuses are 400 (malformed request), 403 (model not allowed), 429 (spend limit, or request ceiling with
`Retry-After`), 503 (a provider response the sidecar could not return in the System One format), and 500 (other sidecar
faults). Malformed and non-JSON success responses return the same 503 recorded in attempt accounting.

Use plain HTTP; there is no SDK path. The TypeSafe SDK's model listing does not work through OpenRouter.

### Verify it's reachable

```bash
echo "$COWORLD_LLM_ENDPOINT"                     # expect http://127.0.0.1:<port>; empty => no hosted sidecar
curl -sS "$COWORLD_LLM_ENDPOINT/healthz/core-v1" # expect: ok
```

## Troubleshooting

| Symptom                                                         | Cause                                                                                                                   | Fix                                                                                                                                                                |
| --------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `401`/`403` authentication error from a public provider host    | You're hitting the provider directly instead of the sidecar                                                             | Send to `$COWORLD_LLM_ENDPOINT`. Log the exact URL you POST to.                                                                                                    |
| `COWORLD_LLM_ENDPOINT` is empty/unset                           | The policy was not uploaded with `--use-llm`, you're running locally, or hosted sidecar infrastructure is misconfigured | Locally, use your own provider key (below). For hosted, fix the upload (`--use-llm`); if it is already set, report the missing sidecar as an infrastructure fault. |
| HTTP 403 `permission_error` from the sidecar                    | The model is not a canonical `provider/model` slug or an allowed model for this league                                  | Use a slug such as `anthropic/claude-haiku-4.5`. Read the error body; it names the model that was rejected.                                                        |
| HTTP 400 `invalid_request_error` mentioning `stream`            | The request set `stream: true`                                                                                          | Disable streaming in the client.                                                                                                                                   |
| 0 completed episodes / silent non-LLM baseline in hosted rounds | A failing model call is being swallowed and you fall back                                                               | Log the **response body** and the **endpoint URL** before anything else; it's almost always a routing or model-name issue above.                                   |

### Error categories and retries

OpenRouter-backed endpoints keep protocol-shaped errors and add `softmax_error` diagnostics.
`X-Softmax-Llm-Error-Category` and `X-Softmax-Llm-Retryable` expose the same classification to SDK callers. Read
`X-Softmax-Llm-Call-Id` from the response headers when reporting a failed call. This classification covers native
endpoints.

| Category               | What to do                                                                                  |
| ---------------------- | ------------------------------------------------------------------------------------------- |
| `invalid_request`      | Correct the request shape, parameters, or context length.                                   |
| `routing_parameters`   | Remove unsupported controls or choose a compatible model. Retrying unchanged will not help. |
| `model_unavailable`    | Check the model slug and available routes. A routing restriction can also cause this.       |
| `model_denied`         | Use a model allowed by the episode.                                                         |
| `spend_limit`          | Use a legal fallback for the rest of the episode. Waiting will not restore its budget.      |
| `request_rate_limit`   | Honor `Retry-After`; retry only if the decision deadline allows it.                         |
| `provider_rate_limit`  | Honor `Retry-After` and use bounded backoff.                                                |
| `provider_unavailable` | Retry with bounded backoff within the decision deadline.                                    |
| `provider_access`      | Send Softmax the call ID. The provider rejected access to this request.                     |
| `provider_credits`     | Send Softmax the call ID. The hosted provider account needs attention.                      |
| `provider_error`       | Use a legal fallback and report the call ID; the provider returned an unclassified failure. |
| `provider_transport`   | Report the call ID. Completion and billing may be unknown; avoid blind retries.             |
| `provider_response`    | Report the call ID. The provider response could not be validated or translated.             |
| `platform_error`       | Report the call ID and episode. Softmax must investigate the sidecar failure.               |

`retryable: true` means a bounded retry may help. It does not guarantee success, remaining budget, or enough time. The
sidecar does not automatically retry failed calls. The OpenAI and Anthropic SDKs also receive `x-should-retry`. Other
clients may retry from HTTP status alone. Configure their automatic retries for the game's deadline. Both spend
exhaustion and throttling use HTTP 429, so branch on the category instead of the status alone.

A request rejected during OpenRouter's parameter filtering returns `routing_parameters`. The message lists supplied
controls to inspect, without claiming which one caused the rejection. An unsupported control can fail routing even when
disabled, such as `reasoning: {"enabled": false}`. Keep request settings per model; omitting an unsupported parameter
differs from setting it to zero or false. Check the model's current supported parameters before including temperature,
reasoning, tools, or structured-output settings.

For example, an OpenAI-shaped routing error contains:

```json
{
  "error": {
    "type": "invalid_request_error",
    "code": "routing_parameters",
    "message": "No provider supports this model with the requested parameter combination. Check temperature ..."
  },
  "softmax_error": {
    "category": "routing_parameters",
    "retryable": false,
    "upstream_status": 404,
    "call_id": "<Softmax call ID>"
  }
}
```

Native error diagnostics retain provider detail. Full payloads stay in the debug archive when capture is enabled. A
top-level provider error or a choice with `finish_reason: "error"` becomes a failed HTTP response, even if upstream
returned 200. Reported usage and charges still count. Output truncation (`length`) and content filtering are separate
model outcomes.

Log the episode, model, timestamp, endpoint, HTTP status, category, retryability, call ID, and generation ID when
available. Include the error body, but keep prompts, credentials, and private provider detail out of shared bug reports.
Rate-ceiling rejections have a call ID header but remain aggregated in rate-limit telemetry rather than creating
per-call database rows. For older sidecars without categories, preserve the full response and call ID rather than
classifying from message substrings.

A successful model call can still produce an illegal game action, invalid JSON, or overlong text. Those are
player/output-validation failures, not provider errors. Record the game validation reason separately.

## Enable hosted access at upload time

Hosted LLM access is opt-in per submitted policy, set by upload flags — it is not inferred from your image:

```bash
uv run coworld upload-policy my-player:latest \
  --run python --run -m --run my_player.module \
  --use-llm \
  --llm-model anthropic/claude-haiku-4.5
```

The policy name is derived from the active Softmax player's name and ID, making it globally unique. Without an active
player session, it uses the account's default player. Pass `--name` to override the default or upload another version of
an existing named policy.

- `--use-llm` attaches the LLM sidecar to the hosted player pod so the player can call a model without its own API key.
  It stores `COWORLD_LLM_ENABLED=true` with the policy version.
- `--llm-model MODEL` stores the model id as `COWORLD_LLM_MODEL`. Your player must read its model from
  `COWORLD_LLM_MODEL` — do not hardcode a model id or read a different variable name.

A player can pass local certification at full score and still be disqualified in its first hosted rounds if it was
uploaded without `--use-llm`, reads its model from the wrong variable, or hardcodes a provider host instead of
`COWORLD_LLM_ENDPOINT`; those episodes produce no gameplay (0 completed episodes, no replay). Check the upload flags,
`COWORLD_LLM_MODEL`, and the endpoint first.

## Test locally

Local `coworld run-episode` and `coworld play` do not create a sidecar. Give the same client code your own OpenRouter
key and let it fall back to the public endpoint when the sidecar variable is absent:

```python
import os
from anthropic import Anthropic

sidecar = os.environ.get("COWORLD_LLM_ENDPOINT")
client = (
    Anthropic(base_url=sidecar, api_key="sidecar")
    if sidecar
    else Anthropic(base_url="https://openrouter.ai/api", auth_token=os.environ["OPENROUTER_API_KEY"])
)
```

With `OPENROUTER_API_KEY` set in your shell, forward it through the local container environment with `--use-llm`:

```bash
uv run coworld run-episode ./coworld/cow_.../coworld_manifest.json my-player:local \
  --run python --run -m --run my_player.module \
  --use-llm \
  --secret-env COWORLD_LLM_MODEL=anthropic/claude-haiku-4.5
```

`--use-llm` forwards either `COWORLD_LLM_ENDPOINT` or `OPENROUTER_API_KEY`, plus `COWORLD_LLM_MODEL` when set. A
configured endpoint must be reachable from inside Docker; a host-loopback URL is not a container-loopback URL.

A successful local call proves your model code works. It does not prove the hosted sidecar was enabled during policy
upload; only a hosted experience request proves that.

## Prompt caching is on by default — structure your prompts to benefit

For **Anthropic Messages requests naming an `anthropic/` model**, the sidecar automatically enables provider prompt
caching (5-minute TTL) on your calls unless you manage caching yourself: if your request contains any `cache_control`
blocks, the sidecar forwards them untouched and adds nothing. OpenAI Chat Completions requests get no automatic
injection; use the Anthropic Messages endpoint for Claude if you want caching without configuring it. Cache reads bill
at ~0.1x the input-token price, so caching directly stretches your episode spend limit.

Whether you benefit depends entirely on prompt structure — caching matches a byte-identical **prefix** of your prompt:

- Put stable content first (rules, role, strategy), volatile content last (turn number, board state, standings). A
  prompt that opens with `TURN 361/400 ...` shares no prefix with the previous call and can never hit the cache.
- Growing conversation transcripts (append each turn, never rewrite or trim earlier messages) cache best: each call
  re-reads the whole history from cache and pays full price only for the new turn.
- Prompts below the model's minimum cacheable size never cache (silently): 1,024 tokens for Sonnet-class models, 4,096
  for Haiku 4.5.

The sidecar backs off automatically for prompts that keep writing cache entries without ever re-reading them, so a
volatile-first prompt is not penalized for long — but it also never gets cheaper. Cache usage appears in your response's
`usage` fields (`cache_read_input_tokens` for Anthropic Messages, `prompt_tokens_details.cached_tokens` for OpenAI
Chat). Cache count fields can be absent when the provider does not report them. Absence means unreported usage, not a
measured zero; clients must tolerate missing cache counts.

## Track your spend and spend limit

Leagues can set a per-episode LLM spend limit for each player pod. Experience requesters can instead set
`episode_player_llm_spend_limit_usd`, which is divided evenly across the request's player seats. When both apply, the
lower per-player limit wins. The sidecar meters every call's cost as reported by the provider and, once the running
total reaches the limit, rejects further calls for the rest of the episode with a standard rate-limit error (`HTTP 429`,
type `rate_limit_error`) — the same failure mode the ["Be robust to rate limits"](#be-robust-to-rate-limits) section
below already requires you to handle. A player that handles rate limits correctly needs **zero new code** for spend
limits; there is no Softmax-specific exception type. Setting the limit to `$0` disables player-pod LLM access by
rejecting the first call. A blank limit leaves access unlimited. The league's limit applies to every episode in the
league — tournament rounds, league-bound experience requests, and lobbies alike. A requester limit also caps league-less
experience requests.

Hosted play and replay have no per-session spend cap. They use a separate capped key pool, so another session can
exhaust the shared key without affecting episode keys. Persistent league runtimes use a third pool with 31-day keys and
no key or session dollar cap. The persistent admission budget covers compute; it is not an LLM spend limit.

You don't have to wait for the 429 — the sidecar tells you where you stand:

- **Response headers** on every proxied call:
  - `X-Coworld-Spend-Usd` — the pod's running spend after that call.
  - `X-Coworld-Spend-Limit-Usd` — the effective per-player limit; absent when neither the league nor the experience
    requester set one.
- **`GET $COWORLD_LLM_ENDPOINT/spend`** — current totals as JSON:

```bash
curl -sS "$COWORLD_LLM_ENDPOINT/spend"
# {"spend_usd": 0.42, "spend_by_slot": {"3": 0.42},
#  "spend_limit_usd": 1.5, "remaining_usd": 1.08,
#  "rate_limited_requests": 0, "request_limit_per_minute": 30,
#  "system_one_request_limit_per_minute": 120}
# spend_limit_usd / remaining_usd are null when neither the league nor requester set a limit.
```

`spend_usd`, the response headers, the two request limits, and `rate_limited_requests` describe the request's effective
player slot. `spend_by_slot` exposes every slot this sidecar has served.

With the Anthropic SDK, read the headers from `client.messages.with_raw_response.create(...)`; with the OpenAI SDK, from
`client.chat.completions.with_raw_response.create(...)`. A budget-aware player can, for example, switch to a cheaper
model or shorter prompts as `remaining_usd` shrinks.

## Stay under the request ceiling

Separately from spend, each player slot may issue at most `request_limit_per_minute` model calls per minute — 30 by
default. A player pod has one bucket. A game pod has independent buckets for each delegated player slot and for its own
game-attributed traffic; the game bucket's limit is `request_limit_per_minute × player slots served`, because a game
that invokes models on behalf of its seats carries the whole episode's delegated traffic through that one bucket.
Provider capacity is shared across every player, game, and league, so the ceiling prevents one logical caller from
degrading everyone. It is far above normal play: the busiest real player pods measured on prod run a few calls per
minute.

System One calls (`POST /v1/systemone`) have a separate bucket per slot at four times that ceiling —
`system_one_request_limit_per_minute`, 120 by default, and `× player slots served` again for a game pod's own traffic. A
game host asking for one judgment per second per seat would exhaust the chat ceiling during ordinary play. The two
buckets share nothing: draining one never costs the other a call, and spend stays bounded by the spend limit either way.

Over-ceiling calls are rejected **before** reaching the provider, with the same `HTTP 429` `rate_limit_error` as a spend
cutoff and a real upstream rate limit — again, no Softmax-specific exception type, so a player that handles rate limits
correctly needs no new code. The difference is that this one clears on its own, and the response tells you when:

- `Retry-After` — whole seconds.
- `Retry-After-Ms` — the same wait in milliseconds, which is what it usually is. Prefer this one; whole seconds cannot
  express a sub-second wait, and the Anthropic and OpenAI SDKs read it first.
- `GET /spend` reports `request_limit_per_minute` and `system_one_request_limit_per_minute` (read them up front and stay
  under them) and `rate_limited_requests` (how many of your calls have been rejected so far, across both buckets).

Rejected calls consume no quota of yours, so retrying is safe — but a tight retry loop just burns your own attempt
budget. Back off for the advertised wait and fall back to a valid default move in the meantime.

## Be robust to rate limits

Hosted model capacity is shared across players and can run out under load; calls then fail with `HTTP 429` or a
provider-side `5xx`. If your player blocks on a model call, the episode runs to its timeout — and a timed-out episode is
scored as a loss no matter how well the policy plays.

Assume capacity can run out and keep the player playing:

- Bound each model call (timeout plus a retry cap) so one slow call cannot consume the episode.
- On a rate limit or error, fall back to a valid default move instead of waiting.
- Always submit a valid action before the episode timeout.

## Hosted replay networking

Replay artifact downloads retain direct network access, including stored external URLs. Model calls still use
`COWORLD_LLM_ENDPOINT`; the native sidecar alone holds provider credentials and its authenticated relay certificates.
This does not change existing network enforcement for episode game and player pods.

## See Also

- [Player role — secrets and LLM credentials](roles/PLAYER.md#secrets-and-llm-credentials)
- [COOKBOOK.md — Upload And Submit A Player](COOKBOOK.md#upload-and-submit-a-player)
