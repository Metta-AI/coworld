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
| source-resolves | auto | whether each runnable declares a source_url that resolves to publicly accessible source | source availability is recorded without gating certification | For every runnable, record a typed result: resolved, unresolved, unsupported, or not_declared. GitHub source_url values are fetched at the declared ref or repository default branch and checked for a Dockerfile at that path or an ancestor directory. Full commit SHAs are preferred for stable provenance; omitted or unverifiable sources remain visible in the transcript but do not prevent graduation. |
| images-reachable | auto | every declared image is pullable or inspectable | all images reachable | Run docker image inspect locally and fall back to docker manifest inspect for remote images. |
| fixture-conforms | auto | the certification fixture validates against game.config_schema after runner token injection | fixture schema validates | Inject synthetic runner tokens into certification.game_config and validate the concrete fixture against the manifest's game.config_schema before launching containers. |
| smoke-episode | auto | the game and certification players run one episode | episode completes | Launch the game plus the certification players from the manifest fixture and run a single episode to completion. |
| results-conform | auto | episode results validate against results_schema | schema validates | Load the episode results artifact and validate it against the manifest's results_schema. |
| replay-present | auto | a replay artifact was produced | replay file exists | Confirm the smoke episode wrote a replay artifact to the workspace. |
| replay-loadable | auto | the replay artifact can be loaded by the game replay server | replay server emits a frame | Start the game image in replay mode with COGAME_LOAD_REPLAY_URI, verify GET /client/replay, and wait for a frame from the /replay WebSocket. |
| players-run | auto | every declared player actually started on the smoke episode (not just declared) | each declared player runs, not just resolves | Confirm the smoke episode left launch logs for the game and for every declared player via at least one certification slot. |
| supporting-roles | auto | declared supporting roles satisfy the currently implemented Executable checks | reporter references validate and commissioners pass; unavailable harnesses are recorded as inert | Statically validate declared reporter references (platform references are recorded; wasm references must name a non-empty component inside the package and declare purpose, world, and typed outputs — full semantic validation happens at platform submission); probe declared commissioners over /healthz and /round with schedule_rounds_request; record graders and diagnosers as declared but harness unavailable; skip optimizers for Executable. |
