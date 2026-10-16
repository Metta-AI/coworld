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
  --llm-endpoint https://inference.distillabs.ai/v1 \
  --llm-api-key-env DISTILLABS_API_KEY
```

Set the provider key locally before uploading. For OpenRouter, omit endpoint/key flags and use its canonical model slug.
Upload sends your locally built image; no registry login or image push is required.

Edit `player.py` for strategy, `inference.py` for generation settings, and the Dockerfile for dependencies. The default
client calls Chat Completions with JSON output; check your provider supports its generation options. For another
protocol, replace the client and declare your provider's `--https-host`. See
[Call a hosted model](https://softmax.com/docs/coworld/build-a-player/hosted-llm) for network access and fresh
direct/league Experience Requests. Verify model calls and accepted replay actions before submitting.

The existing client accepts `PARLEY_ENDPOINT` and `PARLEY_MODEL` instead of the sidecar's `COWORLD_LLM_ENDPOINT` and
`COWORLD_LLM_MODEL`. `PARLEY_API_KEY_ENV` names your credential variable; `PARLEY_COMPLETION_PATH` defaults to
`/v1/chat/completions`. A loopback model server needs neither `--https-host` nor `--use-llm`.

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
