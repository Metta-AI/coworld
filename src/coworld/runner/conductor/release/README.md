# Scott's GOTA rollout

Experimental; owned by Scott (`@macromackie`). Production use is limited to Scott's approved GOTA XP pilot. Coordinate
with Scott before adding consumers, games, users, or production dependencies. APIs may change.

The release pin in `gota.json` selects the October 6 GOTA version from the production Coworld catalog. `runtime.json`
supplies the installed command, qualified policy format and a bounded packaging smoke. The smoke uses idle policies; it
does not establish representative throughput or policy isolation.

The image has two stages. `adapter` contains the pinned game, Node and Metta's adapter. Foundry adds its checked native
runner to that immutable base. `runtime` is the complete image used for local qualification with `--runner`. The adapter
writes player-seats/2. Only bind games qualified for that format; annotations and policy artifacts are not collected by
this integration yet. The manifest's player-seat capability is accepted without forwarding arbitrary environment values.

Follow the [pilot ownership guidance](../../../../../../../.github/CONDUCTOR.md). Publication is restricted to Scott,
including reruns.

## Release order

1. Merge the routing and image-release PRs. Run **Release experimental Conductor GOTA adapter (Scott only)** on current
   Metta main. It builds and runs the real game without network access, saves the image, then publishes those same bytes
   to private `ghcr.io/metta-ai/coworld-conductor-gota`. Record its immutable digest from the workflow summary.
2. In the package's **Manage Actions access**, grant `Metta-AI/foundry` read access. Keep package visibility private.
   Foundry's workflow uses its own `GITHUB_TOKEN`; no personal token or Metta publication credential is shared.
3. Follow Foundry's `workspaces/conductor/worlds/deployment.md`. Set `CONDUCTOR_GOTA_ADAPTER_IMAGE` to the immutable
   digest, rerun the complete main push Check, and deploy its saved image. Record the returned `native-<image digest>`
   runtime ID.
4. Qualify the hosted runtime before activating the Metta PR. Verify scores and replay against the existing path, burst
   utilization up to the configured slot ceiling, cancellation, lost response recovery, private artifact access and
   denied game egress. Measure a full-length match with representative BASIC policies. Inspect the pinned game's policy
   isolation independently.
5. Create the Metta-owned AWS Secrets Manager JSON record `observatory/conductor-gota` in account `751442549699`:
   `service_token` is the same random credential installed in Foundry's worlds settings, and `runtime` is the deployed
   runtime ID. Never put the credential in Git, a PR or workflow output. External Secrets reads only those two fields.
6. After qualification and secret provisioning, set `conductor.enabled: true` in
   `devops/app-manifests/pilots/conductor-gota.yaml` through a reviewed PR. The prepared configuration stays disabled
   until then: enabling it creates required secret references even when every user flag is off. All API and round-runner
   replicas must finish rolling before proof. In the existing admin flags UI, enable
   `experimental-conductor-xp-requests` for Scott's user ID only. Submit a normal private XP request using this version,
   then verify its `conductor_jobs.run_id`, scores, replay and route-selection log. Verify that a user with the flag
   off, a non-team requester and an unqualified version keep Kubernetes. Ask Scott for more info.

The API and round runner admit ordinary user XP. The API runs Conductor reconciliation. Tournament requests remain
ineligible for Conductor. New GOTA versions do not inherit this binding. Machine and commissioner tokens do not inherit
Scott's user identity.

For rollback, disable Scott's user flag override. Each admission batch evaluates current flags; a batch that has already
read its flags can still admit work. Leave `conductor.enabled`, origin, credential and runtime in place until accepted
jobs and remote cleanup finish. Do not repoint the runtime secret while jobs are pending. The first hosted rollout is
manual; image or runtime changes require draining before redeployment.

## Local proof

Build a complete image using the checked Foundry `server.mjs` and `gota.json`'s game image, then run the existing
`examples/gota.json` celld scenario. The integration README documents the real Postgres/S3 XP test. For a production
manifest snapshot, set `CONDUCTOR_QUALIFICATION_MANIFEST` to an untracked JSON record containing `manifest`,
`manifest_hash` and `public_image_uri`. The test uses the full game configuration and canonical hash while resolving its
registered image to the immutable URI, as production admission does. Keep credentials out of that record.
