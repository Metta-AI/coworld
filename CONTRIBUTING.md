# Developing Coworld

Start with the [package map](AGENTS.md) and [runtime decision guide](src/coworld/docs/PLAYER_RUNTIMES.md).

## API requests

Use the Coworld CLI or [CoworldApiClient](src/coworld/api_client.py) for platform requests. The client appends
`/observatory` to the configured API root. On softmax.com the resulting base is `https://softmax.com/api/observatory`,
so v2 requests use `/api/observatory/v2/...`.

A Next.js HTML 404 from `/api/v2/...` can mean the URL skipped `/observatory`; check the path before debugging
credentials. Authenticate with `Authorization: Bearer <token>`.

## Manifest changes

Keep role documentation, templates, generated schemas, certifier checks, and consumers in step when changing a role. Use
[types.py](src/coworld/types.py) as the schema source and follow the
[manifest guide](src/coworld/docs/COWORLD_MANIFEST.md). Public package documentation must work from an installed wheel;
avoid private repository paths and retired CLI commands.

## Runtime and replay verification

Exercise local episode changes through the actual CLI, generated request, artifact workspace, and player networking. Use
the runtime-specific verification instructions in the [lifecycle guide](src/coworld/docs/LIFECYCLE.md).

Keep replay routing and materialization with their owning backend endpoints. Verify the embedded viewer, preserve replay
parameters across proxies, and resolve assets against the episode's recorded Coworld version. Follow the
[static replay viewer guide](src/coworld/docs/STATIC_REPLAY_VIEWERS.md) for current bundle and browser behavior.

For deployed image changes, check build triggers and the running image digest. For Kubernetes authentication failures,
verify the client headers and token audience in the deployed image before changing permissions.

## Contributor Parley endpoints

`tests/test_parley_endpoint_system.py` exercises player initialization, image building, endpoint registration, a
complete hosted five-seat game, and private capture readback. Run the real local stack with
`metta dev up --full-coworld`, upload the published Parley manifest there, and authenticate a local USER at the frontend
proxy. Enable the backend's explicit
[local checkpoint routing profile](../../workspaces/observatory/platform/packages/execution/README.md#trusted-trained-model-inference),
including its trusted routes Secret, sidecar image, mTLS relay, and HTTPS artifact store. An empty checkpoint route map
supports registered contributor endpoints without a merchant key. The default local stack does not enable hosted
inference.

Set `METTA_PARLEY_SYSTEM_SERVER` to that local proxy's API root, `METTA_PARLEY_SYSTEM_COWORLD` to the resulting local
Coworld ID, and `METTA_PARLEY_SYSTEM_GAME_IMAGE` to its downloaded game image. Set `METTA_PARLEY_SYSTEM_ENDPOINT` to the
contributor's public HTTPS base URL, including `/v1`, and `METTA_PARLEY_SYSTEM_MODEL` to the served model name.
`METTA_PARLEY_SYSTEM_API_KEY_ENV` optionally names the environment variable containing its key.

```bash
nix develop -c uv run metta pytest packages/coworld/tests/test_parley_endpoint_system.py -v -n 0 -p no:importnb
```

The test creates two local policies and one private request. It leaves command logs, request IDs, and the private player
artifact under pytest's temporary directory. It requires a successful game, replay, platform call IDs, and exact seeded
capture validation. The provider must accept sampling seeds and produce legal Parley actions. A protocol simulator can
diagnose routing separately, but does not qualify a model or establish playing strength. Never use production as the
test server; league requalification follows successful endpoint verification.

## Hosted artifact resource proof

`tests/test_hosted_artifact_resources_system.py` submits a private two-seat Paint Arena episode to an isolated local
`metta dev up --full-coworld` stack. It checks live pod requests and limits, completion, replay, scores, and exact
streamed artifact sizes and hashes. Authenticate a local team USER through the frontend proxy first; artifact checks use
explicit elevated reads against that same local server.

Set `METTA_COWORLD_ARTIFACT_SYSTEM_CONFIG` to a JSON file containing `server`, `namespace`, `coworld_id`, `policy_ref`,
and `expected_artifacts`. Each expected artifact has `kind`, `size_bytes`, and `sha256`. Upload the game and policy
through the normal CLI before running the test; use a fixture that emits large events and trajectory files. The test
accepts only a localhost server and an isolated `jobs-*` namespace on OrbStack. It saves the request, episode, and
observed pod specifications in pytest's temporary directory. To verify a lowered deployment default, start the stack
with `COWORLD_PLAYER_MEMORY_LIMIT=256Mi` and set the proof's `player_memory_limit` to `512Mi`. The admitted local player
request must remain schedulable.

```bash
nix develop -c uv run metta pytest packages/coworld/tests/test_hosted_artifact_resources_system.py -v -n 0 -p no:importnb
```
