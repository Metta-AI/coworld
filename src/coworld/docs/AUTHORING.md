# Authoring A Coworld

This is the end-to-end guide for building a new Coworld and proving it works: design the game, implement the game
container and bundled players, write the docs, package everything into a manifest, test it locally, upload it, and
verify it runs hosted. Hand this document to someone with Docker, Python, and this package installed and they should be
able to go from an empty directory to a hosted Coworld with a playable replay.

This guide is the narrative spine. The exact contracts live in the reference docs it links to — the
[game role](roles/GAME.md), the [player role](roles/PLAYER.md), the [manifest guide](COWORLD_MANIFEST.md), the
[lifecycle](LIFECYCLE.md), and the [artifact contracts](artifacts/README.md). When this guide and a contract doc
disagree, the contract doc and the generated [manifest schema](../coworld_manifest_schema.json) win.

Throughout, [Paint Arena](../examples/paintarena/README.md) is the worked example: a complete Coworld in one directory,
shipped inside this package. The [starter templates](../templates/README.md) provide per-role scaffolds. When a step
below feels abstract, open the corresponding Paint Arena file and read it alongside.

## The Ladder Of Proof

Coworld development is a loop, not a checklist: exercise a surface, find what is broken, fix it, exercise it again. Each
rung below catches failures the previous rung cannot, and each is cheaper than debugging on the rung above it:

1. **Engine tests** — deterministic, no containers. Prove the rules and the seed discipline.
2. **`coworld run-episode`** — headless local episodes. Prove the container contract and the artifacts.
3. **`coworld play`** — local browser play. Prove the human-facing surfaces.
4. **`coworld certify`** — the automated packaging gate. Prove the manifest, images, players, and replay together.
5. **`coworld upload-coworld`** — publish. Reuses the exact successful certification and pushes.
6. **A hosted experience run** — the only proof that counts as "live": episodes complete, scores are real, and the
   replay actually plays in a browser.

Do not skip rungs, and do not declare a rung passed without reading its actual output — the results file, the replay in
a browser, the logs. "The container started" is not evidence; "the results validate and the replay plays" is.

## Step 0: Design Before Code

Settle these on paper before writing the game. Every one of them is expensive to change after the manifest exists:

- **Seat count.** How many players does an episode seat? Fixed, or a range? This flows into the `tokens` bounds in your
  config schema, the `players` array, your variants, and your certification fixture.
- **The win metric.** What does `results.scores` mean, and can a policy author tell from one episode whether they
  improved? A Coworld exists to power a player-improvement loop; a score that doesn't discriminate between better and
  worse play makes the whole loop useless.
- **Hidden information.** What does each seat see, and what does a spectator see? Decide the redaction rules now: the
  per-seat observation on `/player`, the spectator stream on `/global`, and the replay must each show exactly what their
  audience is allowed to see. A pinned, publicly visible seed can let a player re-derive hidden state — if your game has
  hidden information, random per-episode seeds are a security property, not just a variety feature.
- **Turn structure.** Simultaneous or sequential? What happens when a player is slow, disconnected, or sends an illegal
  action? Design the fallback behavior (see the degradation rules in Step 1) as part of the rules, not as an
  afterthought.
- **The baseline.** What is the always-legal, zero-intelligence action a seat takes when its player is absent or broken?
  You will bundle at least one baseline player built on it, and your game host will fall back to it.

**The determinism invariant.** The initial state must be a pure function of the seed, and the state evolution a pure
function of state plus actions. No wall-clock reads, no ambient randomness — route all randomness through a PRNG seeded
from the config. This single invariant is what makes everything downstream work: reproducible tests, meaningful
certification, replay/episode parity, and seeded hosted runs. Keep the seed **optional** in your config schema: absent
means the game mints a fresh random seed (board variety across episodes), present means exactly reproducible. Never
coerce an absent seed into a string like `"undefined"` or a constant default — both collapse every episode onto one
board, and that class of bug ships silently because everything still "works".

For the design method behind good Coworlds — how the game, graders, reporters, and optimizer surface derive from what
you want players to learn — read
[Coworld design principles](../../../docs/coworlds-expert-agent/knowledge/coworld-design-principles.md).

## Step 1: Implement The Game Container

The game is a long-running container that owns the episode. Its full HTTP/WebSocket/artifact contract is in the
[game role doc](roles/GAME.md); the runner-injected environment (`COGAME_CONFIG_URI`, `COGAME_RESULTS_URI`,
`COGAME_SAVE_REPLAY_URI`, `COGAME_PLAYER_FAILURE_URI`, `COGAME_LOAD_REPLAY_URI`, `COGAME_HOST`/`COGAME_PORT`) and the
required routes (`/healthz`, `/player`, `/global`, `/client/*`) are defined there. Start from the
[game template](../templates/README.md) or Paint Arena's `game/server.py`.

Beyond the contract, these design rules separate a Coworld that survives hosted play from one that hangs its first
league round:

- **Fail loud at startup.** If a required env var or config field is missing, crash with a clear error. A game that
  limps up half-configured produces artifacts nobody can interpret.
- **Degrade, never hang.** Hosted episodes run under a hard time deadline, and a hung episode wastes everyone's slot.
  Bound every wait: a connect deadline for players to join, a per-turn action timeout, and a bounded retry count for
  invalid actions. When a bound is hit, play the baseline action for that seat and move on. A seat with no player at all
  must cost bounded time, not one full timeout per turn for the whole episode.
- **An illegal action is the player's failure, not the game's.** Validate every incoming action against both its schema
  and situational legality. On failure, tell the player why and re-request (bounded), then fall back to the baseline.
  Never crash the episode and never silently accept an illegal move — both destroy the improvement loop.
- **Write artifacts last, and completely.** Results must validate against your `results_schema`; replay bytes must be
  loadable by the same image in replay mode. Anything a player container needs to do at episode end (final messages, its
  own artifact upload) must happen before you finish writing game artifacts — hosted runners tear player pods down as
  soon as the game's outputs exist.
- **Replay mode is the same image, restarted.** With `COGAME_LOAD_REPLAY_URI` set, serve `/client/replay` and `/replay`
  and start playback automatically. The replay URI may be an `http(s)` URL, not a local path — load it accordingly. A
  viewer stuck on its loading screen forever is the classic symptom of a replay loader that assumed a local file.
- **Log for the public.** Game stdout/stderr are exposed through the [game logs](artifacts/GAME_LOGS.md) artifact to
  anyone with episode access. Put authoritative state in the structured artifacts, diagnostics in the logs, and secrets
  in neither.

## Step 2: Implement The Bundled Players

Every manifest declares at least one player — the certifying baseline. The player-side contract (the
`COWORLD_PLAYER_WS_URL` WebSocket, secrets, artifact upload) is in the [player role doc](roles/PLAYER.md); scaffold from
the [player template](../templates/README.md) or Paint Arena's `player/player.py`.

Recommendations for the bundled set:

- **Always ship a scripted, no-LLM baseline.** It is deterministic, free to run, and it is what certification and quick
  local episodes should lean on. It also defines the floor every submitted policy must beat.
- **If the game is meant for LLM players, ship an LLM baseline too** — it proves the credential path and gives policy
  authors a working example to fork. Read [BEDROCK.md](BEDROCK.md) before writing the LLM call; getting the endpoint
  wrong fails silently as a non-LLM baseline.
- **Every player you declare must actually run during certification.** `coworld certify` checks that each declared
  player started on the smoke episode, so your certification fixture must seat all of them. Don't declare aspirational
  players.
- **Players are clients, not orchestrators.** A player never writes episode truth; it may upload its own optional
  [player artifact](artifacts/PLAYER_ARTIFACT.md) for debugging.

## Step 3: Write The Docs

Your Coworld's docs are part of its product surface — a policy author codes against them. The manifest gives you
distinct slots with distinct audiences (see [Docs In The Manifest](COWORLD_MANIFEST.md#docs-in-the-manifest)):

- **`game.protocols.player`** — the machine contract: how a player container connects, the exact frame sequence, what an
  observation contains, and the legal decision shapes per phase. This is an operational spec, not prose; a policy author
  should be able to implement a player from it alone. Paint Arena's `game/docs/player_protocol_spec.md` is the model.
- **`game.protocols.global`** — the spectator contract: the read-only stream the live viewer and replay render.
- **`game.docs.readme`** — the durable human guide: what the game is, the rules, strategy notes, how to use or modify
  the bundled players, and game-specific FAQs.
- **`game.docs.pages`** — longer-form pages (a full ruleset, a strategy primer).
- **`game.description`** — the one-paragraph pitch shown in listings.

Keep game docs game-specific: platform concerns (Softmax auth, policy upload, league submission, standings, replays)
belong to the platform's own guides, not yours.

## Step 4: Package It — Compose, Manifest Template, Build

This is the step with the least room for improvisation, and it is where the pieces you built become one uploadable unit.
Three files, all modeled by Paint Arena:

**`Dockerfile` + `compose.yaml`.** A single image usually serves the game _and_ the bundled players — each manifest
runnable selects its entrypoint with its own `run` argv into the same image. The compose file names your buildable
services and pins `platform: linux/amd64` (hosted runners are amd64; images built for other architectures fail or crawl
under emulation). Paint Arena's compose is two services: the game image built from the local context, plus the stock
commissioner image.

**`coworld_manifest_template.json`.** The manifest with image placeholders instead of image tags. Each compose service
maps to a placeholder by name: service `paintarena` → `{{PAINTARENA_IMAGE}}` (uppercase, dashes become underscores). The
template must **not** set `game.version` — the build stamps it. Fill in the sections in the order given by the
[authoring workflow](COWORLD_MANIFEST.md#authoring-workflow), keeping the generated
[schema](../coworld_manifest_schema.json) open in your editor. The invariants that bite new authors:

- `game.config_schema` must require a string-array `tokens` with `minItems`/`maxItems` bounds — runner-injected player
  auth, never authored by you. `variants[].game_config` and `certification.game_config` are token-free; validation
  injects placeholder tokens before checking them. See
  [Game Configs, Tokens, And Player Names](COWORLD_MANIFEST.md#game-configs-tokens-and-player-names).
- If the game displays player names, declare the `players` array (items requiring `name`) so hosted dispatch can
  overwrite the placeholder names with real policy names. Offline configs (variants, certification fixture) carry
  placeholder names, because local runners inject only tokens.
- `game.protocols` needs both `player` and `global` entries.
- Declare at least one variant (the default board players will actually compete on — typically seed-free), and a
  `certification` fixture that seats **every** declared player.
- Every runnable's `source_url` should resolve to a public repo path containing a Dockerfile, pinned to a commit SHA.
  Mutable refs (branches, `/tree/main/`) certify with warnings today; pin anyway — provenance that moves is provenance
  you can't trust.

**The build.** Keep `compose.yaml` and `coworld_manifest_template.json` in the owning project, then run
`coworld build --version <version>`. The command builds and pulls the images, resolves mutable image references,
substitutes placeholders, stamps the version, validates the hydrated manifest, pins owner-repo source URLs to the
current commit, and writes `dist/coworld_manifest.json`. Build from committed, pushed state so the pinned commit is
available to everyone.

**Optional static replay viewer.** To open replays without starting the game image, add a generated browser bundle and
`game.replay_viewer.bundle` to the manifest template. The required `coworld build` hook creates that bundle before the
hydrated manifest is written; shared
game, replay, presentation, and rendering sources keep it in lockstep behaviorally. Follow
[Static Replay Viewers](STATIC_REPLAY_VIEWERS.md) for the complete bundle, manifest, build-hook, sharing, and browser
verification contract.

## Step 5: Test Locally

Work up the ladder. Concrete command recipes are in the
[cookbook](../../../COOKBOOK.md#build-and-run-paint-arena-locally); substitute your manifest for Paint Arena's.

**Rung 1 — engine tests.** Before any container: same seed twice produces identical initial state, and an identical
trajectory under a scripted policy; no seed produces differing states across runs; a reset or new episode mints a fresh
seed. These are the cheapest tests you will ever write against this game and they guard the invariant everything else
stands on.

**Rung 2 — headless episodes.**

```bash
uv run coworld run-episode dist/coworld_manifest.json          # certification fixture
uv run coworld run-episode dist/coworld_manifest.json -n 3     # seed increments per episode
uv run coworld run-episode dist/coworld_manifest.json --variant <id>
```

Then **read the artifacts** in the output directory: the results validate and the scores are plausible; the replay file
exists; the game and player logs show the episode you think happened (players connected, turns advanced, nobody sat in a
timeout loop). If your game takes a seed: a fixed-seed episode run twice yields matching boards; unseeded runs yield
differing boards. The per-episode `game-config` artifact records the seed actually used — confirm from it, not from
assumption.

**Rung 3 — browser play.**

```bash
uv run coworld play dist/coworld_manifest.json
```

Click through every surface a human will see: the player client (join, act, finish), the global viewer, and — via the
replay command `run-episode` prints — the replay viewer. The replay must start playing automatically and loop; per-seat
hidden information must not leak into the global or replay views.

**Rung 4 — certify.**

```bash
uv run coworld certify dist/coworld_manifest.json
```

Certification runs the ordered, automated transcript in
[`coworld-executable.transcript.md`](../transcripts/coworld-executable.transcript.md): manifest schema, source refs,
image reachability, fixture validation, a smoke episode with every declared player, results conformance, replay present
and loadable, and probes of declared supporting roles. Two expectations to calibrate:

- **A low or zero certification score is normal.** The fixture is a protocol smoke check, not the mission — it proves
  the machinery runs, not that anyone played well.
- **Certification is necessary, not sufficient.** It waits for one frame from the replay server; only you can confirm
  the replay _viewer_ shows the right game. Open the printed replay URL and watch it before uploading.

When a step fails, fix the root cause and re-run the whole command — the transcript is cheap and order matters.

## Step 6: Upload

```bash
uv run softmax login       # once
uv run coworld upload-coworld dist/coworld_manifest.json
```

Upload reuses the successful certification when the manifest, images, transcript, and certifier are unchanged. If any of
them changed, it certifies before creating or pushing a Docker archive. It then pushes the images and manifest. The
first authenticated upload of a `game.name` makes you its name owner; later versions of the same name must come from
you. For post-upload edits (patching docs, bumping an image) see the update recipes in the
[cookbook](../../../COOKBOOK.md#certify-and-upload-a-coworld).

## Step 7: Verify It Hosted

Uploading is not shipping. The closer is a hosted run you inspect end to end — the pieces are in the cookbook
([experience runs](../../../COOKBOOK.md#request-experience-runs),
[watching results](../../../COOKBOOK.md#watch-results-and-find-episodes),
[retrieving artifacts](../../../COOKBOOK.md#retrieve-logs-results-and-replays)); this is the sequence:

1. **Create an experience request** against your uploaded Coworld, seating your bundled players.
2. **Poll it to `completed`.** A request that never completes, or completes with zero episodes, is a packaging or sizing
   bug — go back down the ladder, don't shrug.
3. **Check every episode**: scores present and plausible (all-zero scores from a game that should discriminate means the
   players never really played), and a **non-null replay URL**.
4. **Open the replay in a browser and watch it play.** A replay that exists but never starts is the single most common
   hosted failure, and no automated check fully covers it.
5. **Pull the logs** for the game and each player and read them: every player connected, no seat burned its timeout
   every turn, no silent fallback (an LLM player that couldn't reach Bedrock plays on as a mute baseline — the logs are
   where that shows).
6. **If your game takes a seed**: one seeded request run twice reproduces the board; an unseeded request varies per
   episode. Confirm from each episode's `game-config` artifact and the replay's opening state.

A Coworld is live when a hosted run completes with real scores and a replay a human can watch. Keep that bar for every
subsequent version you upload.

## Step 8: Iterate — Baselines, Then Leagues

The Coworld exists so players can improve against it, and your bundled baseline defines the floor:

- **Tune the baseline headlessly first.** Iterate the scripted policy (or the LLM baseline's prompt and observation
  rendering) with local `run-episode` batches — deterministic seeds, no hosted cost — until it consistently beats a
  trivial policy. Then re-upload and re-verify with one hosted run. A baseline indistinguishable from random makes every
  submitted policy look brilliant and teaches its author nothing.
- **League play is its own verification rung.** When your Coworld enters a league, placement is not proof: confirm
  rounds actually schedule, episodes complete with non-zero scores, standings render, and featured replays play. The
  scheduling side is the commissioner's job — see the [commissioner role](roles/COMMISSIONER.md) and mind the sizing
  contract: the seat count the commissioner schedules for must match what your variants and config schema declare.
- **Version deliberately.** Leagues follow the canonical version of a Coworld; uploading a new version is how fixes
  reach them. Re-run the ladder (certify → upload → hosted run) for every version — the discipline is the same on upload
  ten as on upload one.

## Done Checklist

Your Coworld is done when all of these are true, in this order:

- [ ] Engine tests prove seed determinism (pinned seed reproduces; no seed varies; reset re-mints).
- [ ] `coworld run-episode` completes; results validate; logs show real play; replay artifact exists.
- [ ] `coworld play` works for player, global, and replay surfaces in a browser, with hidden info redacted.
- [ ] `coworld certify` passes, and you watched the certification replay actually play.
- [ ] The manifest pins `source_url`s to pushed commit SHAs and its certification fixture seats every declared player.
- [ ] `coworld upload-coworld` succeeded.
- [ ] A hosted experience run reached `completed` with scored episodes and a replay you watched in a browser.
- [ ] The bundled baseline demonstrably beats a trivial policy.
- [ ] `game.docs.readme` and `game.protocols.*` are complete enough that a policy author needs nothing else from you.

## See Also

- [Coworld concept map](README.md) — roles, statuses, artifact flow.
- [Manifest guide](COWORLD_MANIFEST.md) and the generated [schema](../coworld_manifest_schema.json).
- [Game role](roles/GAME.md) and [player role](roles/PLAYER.md) — the two live runtime contracts.
- [Lifecycle](LIFECYCLE.md) — local and hosted episode lifecycles in detail.
- [Static replay viewers](STATIC_REPLAY_VIEWERS.md) — build and upload a browser-only replay bundle.
- [Cookbook](../../../COOKBOOK.md) — copy-paste recipes for every command this guide names.
- [Paint Arena](../examples/paintarena/README.md) — the complete worked example.
- [Starter templates](../templates/README.md) — per-role scaffolds.
- [BEDROCK.md](BEDROCK.md) — required reading before any player or game calls an LLM.
- [Coworld design principles](../../../docs/coworlds-expert-agent/knowledge/coworld-design-principles.md) — the design
  method behind the checklist.
