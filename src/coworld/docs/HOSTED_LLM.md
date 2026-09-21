# Hosted LLM Calls For Coworld Players

For runtime selection, see [Choose a Player Runtime](PLAYER_RUNTIMES.md). The player-pod upload flags below apply to
`platform-hosted` players. In `game-hosted` mode, the game uses its own sidecar and supplies `X-Coworld-Player-Slot: N`
on every request for seat `N`. File policies have no environment, secrets, or player sidecar; see
[the game contract](roles/GAME.md#hosted-llm-access).

**Status:** live

Players that call an LLM can do so in hosted tournaments **without shipping their own model credentials**. The platform
runs a per-pod proxy (the "LLM sidecar") that holds the real provider key, forwards your calls to
[OpenRouter](https://openrouter.ai), and meters spend against the league's limits.

> ## ⚠️ THE ONE RULE — send every model call to `AWS_ENDPOINT_URL_BEDROCK_RUNTIME`
>
> In a hosted episode your player pod is given the env var **`AWS_ENDPOINT_URL_BEDROCK_RUNTIME`** (e.g.
> `http://127.0.0.1:9100`). The name is historical; the value is the sidecar's base URL. **Every model call must go to
> that endpoint.** The pod has no provider credentials of its own, so a client that calls `api.anthropic.com`,
> `api.openai.com`, `openrouter.ai`, or any AWS host directly fails with an authentication error. Whether the player
> then falls back or breaks depends on the player implementation.
>
> **Don't supply a real API key and don't worry about auth.** The sidecar ignores whatever auth header you send and
> attaches the real key itself. Standard SDKs need a non-empty key to construct a client, so pass any placeholder. Never
> hardcode the host or the port.

## How to make the call

### Detecting that you're behind the sidecar

The presence of **`AWS_ENDPOINT_URL_BEDROCK_RUNTIME`** is the signal that the hosted sidecar is available. Gate on that
env var, not on `USE_BEDROCK`, which is the stored enablement flag rather than a runtime signal.

One exception: if any policy in the episode was uploaded with a `--bedrock-model` value the platform cannot map to an
OpenRouter slug, the dispatcher keeps that whole episode on the legacy lane so those pods are not stranded. On such an
episode the native endpoints below answer HTTP 503 `OpenRouter is not configured`. Naming a canonical slug (or a known
alias) in your own upload keeps you off that path; the failure is caused by another pod's model name, not yours.

The platform adds the sidecar and injects this environment into a hosted player pod when its policy was uploaded with
`--use-bedrock`:

| Env var                            | Value in a hosted, sidecar-backed pod              | What you do with it                                              |
| ---------------------------------- | -------------------------------------------------- | ---------------------------------------------------------------- |
| `AWS_ENDPOINT_URL_BEDROCK_RUNTIME` | the sidecar, e.g. `http://127.0.0.1:9100`          | **Send all model calls here.** Read it; never hardcode.          |
| `BEDROCK_MODEL`                    | the model id from `--bedrock-model`, when provided | Read your model from this when your policy uses the upload flag. |

The pod also receives placeholder `AWS_*` credential and region variables. They exist so that legacy AWS-SDK clients can
construct a request; they carry no access and are stripped by the sidecar.

### Which models you can name

Name models by their canonical OpenRouter slug, for example `anthropic/claude-haiku-4.5`, `anthropic/claude-sonnet-4.6`,
or `amazon/nova-micro-v1`. The sidecar also resolves a configured set of legacy aliases (short names such as
`claude-haiku-4.5` and older provider-specific ids), but new players should use the slug. A model name that is neither a
`provider/model` slug nor a known alias, or that the league does not allow, is rejected with HTTP 403 before any call
leaves the pod. A well-formed slug the provider does not serve is forwarded and fails with the provider's own error
(HTTP 404 or 400), so check the model exists on OpenRouter before you rely on it.

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

client = Anthropic(base_url=os.environ["AWS_ENDPOINT_URL_BEDROCK_RUNTIME"], api_key="sidecar")
resp = client.messages.create(
    model=os.environ["BEDROCK_MODEL"],
    max_tokens=512,
    messages=[{"role": "user", "content": "..."}],
)
```

```python
# Python — OpenAI SDK. The SDK appends /chat/completions, so the base URL includes /v1.
import os
from openai import OpenAI

client = OpenAI(base_url=f"{os.environ['AWS_ENDPOINT_URL_BEDROCK_RUNTIME']}/v1", api_key="sidecar")
resp = client.chat.completions.create(
    model=os.environ["BEDROCK_MODEL"],
    max_tokens=512,
    messages=[{"role": "user", "content": "..."}],
)
```

The same pattern works for the JavaScript SDKs with any placeholder `apiKey`: the Anthropic SDK takes the env var
unchanged as `baseURL`; the OpenAI SDK needs `${endpoint}/v1`, as in the Python example.

### Hand-rolled HTTP

Hand-rolled clients must build the URL from the endpoint environment variable. No auth header is needed:

```bash
curl -sS -X POST "$AWS_ENDPOINT_URL_BEDROCK_RUNTIME/v1/messages" \
  -H "Content-Type: application/json" \
  -H "anthropic-version: 2023-06-01" \
  -d "{\"model\":\"$BEDROCK_MODEL\",\"max_tokens\":512,
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

The request is a JSON object with `model`, `state` (a string, an array, or an object; not a bare number, boolean, or
null), and `questions` (a non-empty object keyed by your own question ids). Each question has a `type`, optional
`instructions`, and `criteria` whose shape depends on the type:

| `type`   | Answers                                   | `criteria`                                                              |
| -------- | ----------------------------------------- | ----------------------------------------------------------------------- |
| `noul`   | the probability that the answer is yes    | optional: an object with `true` and/or `false` descriptions, or null    |
| `choice` | one option, with a probability per option | required: a non-empty object mapping each option label to a description |
| `score`  | a position along ordered levels           | required: a non-empty array of level descriptions, lowest first         |

The sidecar itself rejects, with HTTP 400 before any call leaves the pod, a request without `state` or with missing or
empty `questions`. It does not validate question shapes: a `criteria` of the wrong shape (an object for a `score`, a
string for a `noul`) is forwarded and comes back as the provider's HTTP 400, which names the offending path.

```bash
curl -sS -X POST "$AWS_ENDPOINT_URL_BEDROCK_RUNTIME/v1/systemone" \
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
`Retry-After`), and 500/503 (sidecar or provider fault). The one exception is the plain-text HTTP 503
`OpenRouter is not configured` described above, which every native endpoint returns on a legacy-lane episode.

Use plain HTTP; there is no SDK path. The TypeSafe SDK's model listing does not work through OpenRouter.

### Verify it's reachable

```bash
echo "$AWS_ENDPOINT_URL_BEDROCK_RUNTIME"                     # expect http://127.0.0.1:<port>; empty => no hosted sidecar
curl -sS "$AWS_ENDPOINT_URL_BEDROCK_RUNTIME/healthz/core-v1" # expect: ok
```

## Troubleshooting

| Symptom                                                         | Cause                                                                                                                       | Fix                                                                                                                                                                    |
| --------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `401`/`403` authentication error from a public provider host    | You're hitting the provider directly instead of the sidecar                                                                 | Send to `$AWS_ENDPOINT_URL_BEDROCK_RUNTIME`. Log the exact URL you POST to.                                                                                            |
| `AWS_ENDPOINT_URL_BEDROCK_RUNTIME` is empty/unset               | The policy was not uploaded with `--use-bedrock`, you're running locally, or hosted sidecar infrastructure is misconfigured | Locally, use your own provider key (below). For hosted, fix the upload (`--use-bedrock`); if it is already set, report the missing sidecar as an infrastructure fault. |
| HTTP 403 `permission_error` from the sidecar                    | The model is not a `provider/model` slug, a known alias, or an allowed model for this league                                | Use a slug such as `anthropic/claude-haiku-4.5`. Read the error body; it names the model that was rejected.                                                            |
| HTTP 503 `OpenRouter is not configured` on `/v1/messages`       | The episode was pinned to the legacy lane because a policy in it names an unmappable model                                  | Check every policy's `--bedrock-model`; use canonical slugs. Fall back to a legal action for this episode.                                                             |
| HTTP 400 `invalid_request_error` mentioning `stream`            | The request set `stream: true`                                                                                              | Disable streaming in the client.                                                                                                                                       |
| 0 completed episodes / silent non-LLM baseline in hosted rounds | A failing model call is being swallowed and you fall back                                                                   | Log the **response body** and the **endpoint URL** before anything else; it's almost always a routing or model-name issue above.                                       |

When debugging, **log the response body, not just the status code** — the error body names the exact failure (route,
model, spend, or provider). A bot that logs only `HTTP 403` hides which one it is.

## Enable hosted access at upload time

Hosted LLM access is opt-in per submitted policy, set by upload flags — it is not inferred from your image:

```bash
uv run coworld upload-policy my-player:latest \
  --run python --run -m --run my_player.module \
  --use-bedrock \
  --bedrock-model anthropic/claude-haiku-4.5
```

The policy name is derived from the active Softmax player's name and ID, making it globally unique. Without an active
player session, it uses the account's default player. Pass `--name` to override the default or upload another version of
an existing named policy.

- `--use-bedrock` attaches the LLM sidecar to the hosted player pod so the player can call a model without its own API
  key. The flag keeps its original name; it stores `USE_BEDROCK=true` with the policy version.
- `--bedrock-model MODEL` stores the model id as `BEDROCK_MODEL`. Your player must read its model from `BEDROCK_MODEL` —
  do not hardcode a model id or read a different variable name.

A player can pass local certification at full score and still be disqualified in its first hosted rounds if it was
uploaded without `--use-bedrock`, reads its model from the wrong variable, or hardcodes a provider host instead of
`AWS_ENDPOINT_URL_BEDROCK_RUNTIME`; those episodes produce no gameplay (0 completed episodes, no replay). Check the
upload flags, `BEDROCK_MODEL`, and the endpoint first.

## Test locally

There is no sidecar in local `coworld run-episode` or `coworld play`. Give the same client code your own OpenRouter key
and let it fall back to the public endpoint when the sidecar variable is absent:

```python
import os
from anthropic import Anthropic

sidecar = os.environ.get("AWS_ENDPOINT_URL_BEDROCK_RUNTIME")
client = (
    Anthropic(base_url=sidecar, api_key="sidecar")
    if sidecar
    else Anthropic(base_url="https://openrouter.ai/api", api_key=os.environ["OPENROUTER_API_KEY"])
)
```

Pass the key into the local player container with `--secret-env`:

```bash
uv run coworld run-episode ./coworld/cow_.../coworld_manifest.json my-player:local \
  --run python --run -m --run my_player.module \
  --secret-env OPENROUTER_API_KEY=... \
  --secret-env BEDROCK_MODEL=anthropic/claude-haiku-4.5
```

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

## Track your spend (and the league's spend limit)

Leagues can set a per-episode LLM spend limit for each player pod. The sidecar meters every call's cost as reported by
the provider and, once the running total reaches the limit, rejects further calls for the rest of the episode with a
standard rate-limit error (`HTTP 429`, type `rate_limit_error`) — the same failure mode the
["Be robust to rate limits"](#be-robust-to-rate-limits) section below already requires you to handle. A player that
handles rate limits correctly needs **zero new code** for spend limits; there is no Softmax-specific exception type.
Setting the limit to `$0` disables player-pod LLM access by rejecting the first call. A blank limit leaves access
unlimited. The league's limit applies to every episode in the league — tournament rounds, league-bound experience
requests, and lobbies alike; episodes outside any league are never capped (for experience requests, the requester's
credit allowance is the control).

You don't have to wait for the 429 — the sidecar tells you where you stand:

- **Response headers** on every proxied call:
  - `X-Coworld-Spend-Usd` — the pod's running spend after that call.
  - `X-Coworld-Spend-Limit-Usd` — the league's limit; absent when the league has no limit.
- **`GET $AWS_ENDPOINT_URL_BEDROCK_RUNTIME/spend`** — current totals as JSON:

```bash
curl -sS "$AWS_ENDPOINT_URL_BEDROCK_RUNTIME/spend"
# {"spend_usd": 0.42, "spend_by_slot": {"3": 0.42},
#  "spend_limit_usd": 1.5, "remaining_usd": 1.08,
#  "rate_limited_requests": 0, "request_limit_per_minute": 30,
#  "system_one_request_limit_per_minute": 120}
# spend_limit_usd / remaining_usd are null when the league has no limit.
# system_one_request_limit_per_minute is absent on a legacy-lane episode, where /v1/systemone is not served.
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
Jev judgment takes a fraction of a second, costs a few thousandths of a cent, and is asked by a game host at the game's
own cadence (up to one per second per seat), so the chat ceiling would throttle ordinary play. The two buckets share
nothing: draining one never costs the other a call, and spend stays bounded by the spend limit either way.

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

## See Also

- [Player role — secrets and LLM credentials](roles/PLAYER.md#secrets-and-llm-credentials)
- [COOKBOOK.md — Upload And Submit A Player](COOKBOOK.md#upload-and-submit-a-player)
