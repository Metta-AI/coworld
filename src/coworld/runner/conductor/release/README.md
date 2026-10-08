# Conductor adapter publication

Experimental; owned by Scott (`@macromackie`). Production use is limited to Scott's approved GOTA XP pilot. Ask Scott
for more info before adding consumers, games, users or production dependencies.

Metta publishes an immutable adapter payload containing Node, the game-hosted adapter and `runtime.json`. The payload
contains no game. Foundry combines an approved payload digest with a registered game's published image and its checked
native runner. Each prepared version has its own immutable Modal application; accepted jobs retain that binding.

`gota.json` is the packaging smoke fixture. It does not select production admission or require changes when a new GOTA
version is published. The smoke uses idle policies and does not establish representative throughput or policy isolation.
The adapter writes player-seats/2. Annotations, model access and policy-produced artifacts are not supported.

## Publishing an adapter change

1. Run **Release experimental Conductor adapter (Scott only)** on current Metta main. It builds the payload, tests the
   adapter with the GOTA fixture without network access, and publishes the saved payload bytes to private
   `ghcr.io/metta-ai/coworld-conductor-adapter`.
2. Grant `Metta-AI/foundry` read access in that package's **Manage Actions access**. Keep visibility private. Foundry
   uses its workflow `GITHUB_TOKEN`; no Metta publication credential is shared.
3. Set Foundry's `CONDUCTOR_GAME_ADAPTER_IMAGE` repository variable to the published immutable digest. Follow Foundry's
   `workspaces/conductor/worlds/deployment.md` for preparation and hosted proof. Changing the payload does not replace
   an already accepted runtime or silently rebuild ready versions.

## Publishing a game version

Register the trusted publisher and exact game name once in Foundry. Metta exposes recent public game-hosted versions
whose immutable images have a public mirror. Foundry's discovery workflow prepares unprepared versions outside the XP
request path and publishes readiness only after the deployed function completes a packaging smoke.

A normal XP request from an enrolled team user asks Conductor about the exact publisher, name, manifest and image. Ready
versions can use Conductor; unprepared versions keep Kubernetes. The existing feature flag stays off by default and is
enabled only for Scott's account. There is no per-version Helm value or runtime secret to update.

The Metta AWS secret `observatory/conductor-gota` needs only `service_token`. It authenticates backend requests to
Foundry and must exist before enabling `conductor.enabled`; enabling creates a required ExternalSecret regardless of
user flag settings. Existing unused `runtime` fields can remain during migration. Never write credentials to Git.

For rollback, disable Scott's user flag override. Leave the origin, service credential and all accepted runtimes
available until jobs and remote cleanup finish. A new retry must still qualify for its previously selected platform; it
cannot silently rerun on Kubernetes. Tournament work and machine identities remain outside this pilot.

## Local proof

Build a payload with `--payload-only`, a game plus adapter with `--adapter-only --game-image ...`, or a complete image
with `--runner /path/to/server.mjs --game-image ...`. All modes require `--tag`. The integration README describes the
real Postgres/S3 XP test and the celld scenario.

For a production manifest snapshot, set `CONDUCTOR_QUALIFICATION_MANIFEST` to an untracked JSON record containing
`manifest`, `manifest_hash` and `public_image_uri`. The test uses the full game configuration and canonical hash while
resolving its registered image to the immutable URI, as production admission does. Keep credentials out of that record.
