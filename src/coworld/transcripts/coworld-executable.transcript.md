# coworld-executable.transcript.md

The **Executable** degree transcript: the certifier's ordered, automated procedure for proving that a
Coworld's parts run end-to-end and emit conformant output. It is the canonical, hashable record of *what the
certifier checks* for this degree (`CERTIFIER_PRD.md` §6). Each step has a stable `id` the certifier maps to
an executor; this markdown is the source of truth for *meaning*, the code in `certifier.py` is the
*implementation*.

Every step is `auto` — a robot grants Executable alone (`CERTIFIER_PRD.md` §5).

| id | kind | checks | pass | how |
| --- | --- | --- | --- | --- |
| matriculate | auto | manifest conforms to the Coworld schema | schema validates | Parse the manifest and validate it against the generated coworld_manifest_schema.json; refuse to grade if it does not conform. |
| source-resolves | auto | every declared source_url is pinned to an immutable commit SHA, resolves, and carries a Dockerfile | all pinned sources resolve | For each GitHub runnable source_url, require a full 40-hex commit SHA ref, fetch its contents, and confirm it (or an ancestor directory) contains a Dockerfile. |
| images-reachable | auto | every declared image is pullable or inspectable | all images reachable | Run docker image inspect locally and fall back to docker manifest inspect for remote images. |
| fixture-conforms | auto | the certification fixture validates against game.config_schema after runner token injection | fixture schema validates | Inject synthetic runner tokens into certification.game_config and validate the concrete fixture against the manifest's game.config_schema before launching containers. |
| smoke-episode | auto | the game and certification players run one episode | episode completes | Launch the game plus the certification players from the manifest fixture and run a single episode to completion. |
| results-conform | auto | episode results validate against results_schema | schema validates | Load the episode results artifact and validate it against the manifest's results_schema. |
| replay-present | auto | a replay artifact was produced | replay file exists | Confirm the smoke episode wrote a replay artifact to the workspace. |
| replay-loadable | auto | the replay artifact can be loaded by the game replay server | replay server emits a frame | Start the game image in replay mode with COGAME_LOAD_REPLAY_URI, verify GET /client/replay, and wait for a frame from the /replay WebSocket. |
| players-run | auto | every declared player actually started on the smoke episode (not just declared) | each declared player runs, not just resolves | Confirm the smoke episode left launch logs for the game and for every declared player via at least one certification slot. |
| supporting-roles | auto | declared supporting runnables satisfy the currently implemented Executable role probes | reporters and commissioners pass; unavailable harnesses are recorded as inert | Run declared reporters against the certification episode and validate their report zips; probe declared commissioners over /healthz and /round with schedule_rounds_request; record graders and diagnosers as declared but harness unavailable; skip optimizers for Executable. |
