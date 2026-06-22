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
| source-resolves | auto | every declared source_url resolves and carries a Dockerfile | all sources resolve | For each runnable source_url, fetch its contents and confirm it (or an ancestor directory) contains a Dockerfile. |
| images-reachable | auto | every declared image is pullable or inspectable | all images reachable | Run docker image inspect locally and fall back to docker manifest inspect for remote images. |
| smoke-episode | auto | the game and certification players run one episode | episode completes | Launch the game plus the certification players from the manifest fixture and run a single episode to completion. |
| results-conform | auto | episode results validate against results_schema | schema validates | Load the episode results artifact and validate it against the manifest's results_schema. |
| replay-present | auto | a replay artifact was produced | replay file exists | Confirm the smoke episode wrote a replay artifact to the workspace. |
| purposes-run | auto | every required-purpose runnable actually started on the smoke episode (not just declared) | each required purpose runs, not just resolves | Confirm the smoke episode left launch logs for the game and for every declared player via at least one certification slot. |
