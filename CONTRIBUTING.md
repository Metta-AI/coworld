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
