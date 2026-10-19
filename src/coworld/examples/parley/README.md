# Build your own Parley player

This editable player receives private observations and returns actions for Parley's five-seat `table5` game. The game
owns rules, legality, scores, and deadlines. Qwen evaluation and GPU players consume this same source.

```bash
coworld init player my-parley --example parley
cd my-parley
docker build --platform linux/amd64 -t my-parley:local .
coworld upload-policy my-parley:local --name my-parley \
  --secret-env PARLEY_OPERATOR_PROMPT="Play legal actions and maximize your score." \
  --use-llm --llm-model YOUR_SERVED_MODEL \
  --llm-endpoint https://models.example.com/v1 \
  --llm-api-key-env MODEL_API_KEY
```

Set the provider key locally before uploading. For OpenRouter, omit endpoint/key flags and use its canonical model slug.
Upload sends your locally built image; no registry login or image push is required. For merged checkpoint weights, first
serve them through an OpenAI-compatible runtime you control. Register that runtime's HTTPS base URL and loaded model
name. This player works with contributor-hosted endpoints and requires no Distil Labs account.

Freeze the operator prompt and generation settings in the image when comparing checkpoints:

```bash
docker build --platform linux/amd64 -t my-parley:local \
  --build-arg PARLEY_OPERATOR_PROMPT="YOUR_ORIGINAL_STRATEGY" \
  --build-arg 'PARLEY_INFERENCE={"temperature":0,"seed":42}' .
```

The build validates generation settings. Keep provider credentials out of build arguments; the upload command reads the
named key variable and registers the route privately. A sampling seed is retained in each private capture; it does not
guarantee identical responses across provider deployments.

Edit `player.py` for strategy, `inference.py` for generation settings, and the Dockerfile for dependencies. The default
client calls Chat Completions with JSON output; check your provider supports its generation options. For another
protocol, replace the client and declare your provider's `--https-host`. See
[Call a hosted model](https://softmax.com/docs/coworld/build-a-player/hosted-llm) for network access and fresh
direct/league Experience Requests. Verify model calls and accepted replay actions before submitting.

The existing client accepts `PARLEY_ENDPOINT` and `PARLEY_MODEL` instead of the sidecar's `COWORLD_LLM_ENDPOINT` and
`COWORLD_LLM_MODEL`. `PARLEY_API_KEY_ENV` names your credential variable; `PARLEY_COMPLETION_PATH` defaults to
`/v1/chat/completions`. A loopback model server needs neither `--https-host` nor `--use-llm`.

For providers that reject simultaneous temperature and nucleus sampling, set `"top_p": null` in `PARLEY_INFERENCE`. Set
`"output_format": "text"` to omit `response_format` when the provider does not support it. The player still requires a
JSON game action and records the exact request; these settings do not repair illegal responses.

For schema-constrained providers, set `response_schema` to `{"name": "game_action", "strict": true, "schema": {...}}` in
`PARLEY_INFERENCE`. This sends a Chat Completions `json_schema` response format and requires constrained JSON output.
Retain the exact schema with the inference configuration. A syntax schema does not establish game legality or qualify
on-policy training with a different sampling distribution.

Parley's bundled `/bin/parley-player` sends `PLAYER_PROMPT` to game-owned inference; endpoint flags cannot redirect it.
Upload this project's image as a new policy version and move your prompt to `PARLEY_OPERATOR_PROMPT`. `evidence.py`
records private captures; changing its format or generation settings changes training comparability.

Set `PARLEY_DECODING=legal-actions` for an explicitly constrained player variant. The endpoint must support JSON Schema
decoding. Each native window supplies the shot menu and side-action allowances used to build its grammar. The player
still generates the full action; the game validates it. Unsupported legacy windows fail explicitly. The default,
`PARLEY_DECODING=model`, keeps ordinary JSON-object generation. Compare the variants separately and retain the request
grammar in private captures; constrained captures are evaluation-only for the model-only training importer.

Set `enable_thinking: true` in the `PARLEY_INFERENCE` JSON build argument for a reasoning variant. The endpoint must
return nonempty `message.reasoning_content` separately from final JSON in `message.content`. Only the final action
reaches the game; the original response remains in the private capture. Missing reasoning or an incomplete response
fails the decision. Keep the game's ordinary budgets and qualify the actual endpoint before submitting the variant.

## Verify the hosted endpoint before league submission

Create one direct Experience Request using the new policy version and four frozen scripted opponents on the published
five-seat `table5` release. Keep ordinary sampled rules and manifest budgets. Check that the episode completed, its
replay exists, and the private player artifact contains successful calls with platform call IDs. Compare those IDs and
responses with the provider export. A local Docker call or an accepted upload alone does not prove hosted routing.

Repeat this check for each endpoint/model registration, including i4b and each newly trained arm. Register a new policy
version when changing the endpoint, model, prompt, or generation settings. Existing requests retain their selected
versions. A hosted smoke establishes transport and legal play; league requalification and strength evaluation remain
separate steps.
