# Coworld Game Runtime Contract

This is the canonical contract for Coworld game containers. Player authors usually only need the player protocol linked
from a Coworld manifest; game authors need this file.

A Coworld episode has one game container and one policy/player container per slot. The runner starts the game, gives it
a config, starts the policy containers, records logs, and collects results and replay artifacts. The game owns the
rules. Policies connect over websocket and choose actions.

The public v2 tournament system is container-first: games are containers, submitted policies are containers, and the
manifest describes how those containers fit together into a Coworld episode.

## Hosted Runtime Resources

Hosted Kubernetes runners schedule Coworld containers with explicit resource requests so the scheduler reserves real
capacity for each episode component:

- Game container: 2 CPU and 2Gi memory
- Runner worker container: 2 CPU and 2Gi memory
- Each player container: 2 CPU and 2Gi memory
- Replay container: 2 CPU and 2Gi memory

These are scheduling requests, not CPU or memory limits. A container may use more if the node has spare capacity, but
game and player authors should treat the requested capacity as the portable baseline available in hosted runs.

## Manifest Fields

The `game` object in `coworld_manifest.json` describes the game container:

- `name`, `version`, `description`, and `owner`
- `runnable`: Docker image, optional command, and public environment variables
- `config_schema`: JSON Schema for the runtime game config
- `results_schema`: JSON Schema for the final results file
- `protocols.player`: player websocket protocol docs
- `protocols.global`: live viewer websocket protocol docs

Protocol docs are document objects:

```json
{ "type": "uri", "value": "https://example.com/player_protocol.md" }
```

Use `type: "uri"` for public HTTP(S) docs and `type: "text"` only for deliberately inline docs.

## Player Slots

The game config schema must require a `tokens` field. It must be a string array with equal `minItems` and `maxItems`.
That fixed length is the number of player slots.

Coworld-authored configs, variants, and certification fixtures do not include `tokens`. The runner creates fresh tokens
for each episode and injects them into the concrete runtime config.

The game must reject a `/player` websocket connection when the slot/token pair is not valid for that episode.

## Rollout Mode

For a normal episode, the runner starts the game with:

```bash
COGAME_CONFIG_URI=...
COGAME_RESULTS_URI=...
COGAME_SAVE_REPLAY_URI=...
COGAME_RESULTS_METHOD=PUT    # optional for HTTP(S) output URIs; POST is also valid
COGAME_SAVE_REPLAY_METHOD=PUT # optional for HTTP(S) output URIs; POST is also valid
COGAME_HOST=0.0.0.0
COGAME_PORT=8080
COGAME_LOG_URI=...           # optional
```

The game must support `file://` URIs and HTTP(S) read/write URIs. HTTP(S) output URIs are usually presigned upload URLs,
with `PUT` as the default method.

If `COGAME_LOG_URI` is set, the game should POST log lines to that URL (plain text, one or more newline-separated
lines per request). If it is unset, the game must skip log posting. In either case, the container is free to log to
stdout/stderr as normal. Hosted Coworld episode jobs collect both stdout and stderr from the game pod and each started
player pod; these container streams are independent from `COGAME_LOG_URI`.

In rollout mode, the game listens on `0.0.0.0:8080` and exposes:

- `GET /healthz`
- `GET /client/player?slot=0&token=...&...`
- `WEBSOCKET /player?slot=0&token=...&...`
- `GET /client/global`
- `WEBSOCKET /global`

`GET /healthz` returns 200 when the game is ready.

`GET /client/player` serves a browser client for one slot. `GET /client/global` serves a live viewer. Both client
pages and their websockets follow the contract in [Browser Clients](#browser-clients).

The `/global` websocket must support late viewers. A viewer that joins after the episode starts should receive enough
state to render from that point forward.

The `/player` websocket must allow the same slot to reconnect with the same token while the episode is still running.
The slot's game state survives disconnects. During a disconnect, the game may use no-op actions or another documented
behavior.

### Log visibility

Game container stdout and stderr are surfaced to any user with episode access through the per-episode bundling layer
(see [EPISODE_BUNDLE_README.md](EPISODE_BUNDLE_README.md)). Treat those streams as **public**: do not write secrets,
private credentials, or other confidential information to stdout, stderr, or `COGAME_LOG_URI`. The same rule applies
to the global viewer's `/global` websocket and any browser-served client pages.

Games may expose local-only admin controls by convention:

- `GET /client/admin`
- `WEBSOCKET /admin?...`

The admin route is game-owned. The platform must not expose `/admin` in production.

## Replay Mode

For replay viewing, the runner starts the same game image with:

```bash
COGAME_REPLAY_SERVER=1
```

In replay mode, the game listens on `0.0.0.0:8080` and exposes:

- `GET /healthz`
- `GET /client/replay?uri=<uri>`
- `WEBSOCKET /replay?uri=<uri>`

`GET /client/replay?uri=<uri>` serves a browser replay viewer. The page and its websocket follow the contract in
[Browser Clients](#browser-clients); the `uri` query param carries the replay artifact location end-to-end from the
page URL into the websocket URL. The game loads the replay artifact and handles game-owned replay controls such as
start, stop, seek, or speed changes.

Hosted Observatory replay sessions use the same `/client/replay?uri=<uri>` entrypoint for every Coworld game, so
adding a new Coworld does not require frontend changes to expose its replays.

The replay artifact format and replay websocket protocol are game-owned.

## Browser Clients

Every game container serves both static HTML viewer pages and websockets from the same port. The HTML pages are small
JavaScript shims that open a websocket back to the same game container. This section documents the contract those JS
shims must implement.

The URL families:

| Page (HTML)                            | WebSocket                       | Purpose                       |
| -------------------------------------- | ------------------------------- | ----------------------------- |
| `GET /client/player?slot=…&token=…&…` | `WEBSOCKET /player?slot=…&token=…&…` | Rollout mode: one player slot |
| `GET /client/global`                  | `WEBSOCKET /global`             | Rollout mode: live viewer     |
| `GET /client/replay?uri=…`            | `WEBSOCKET /replay?uri=…`       | Replay mode: replay viewer    |

### Default URL derivation

When the browser loads a client HTML page, that page's JavaScript derives the websocket URL it should open by taking
`window.location.href`, applying two changes, and preserving everything else:

1. Convert protocol: `http://` → `ws://`, `https://` → `wss://`.
2. Replace path: `/client/player` → `/player`, `/client/global` → `/global`, `/client/replay` → `/replay`.

The entire page query string carries over to the websocket URL unchanged. That is how `slot`, `token`, game-owned
params (e.g. `role=scout`), and the replay `uri` all flow from the page URL into the websocket URL.

Example:

```text
page URL:       http://game-host:8080/client/player?slot=0&token=abc&role=scout
websocket URL:  ws://game-host:8080/player?slot=0&token=abc&role=scout
```

### The `address` override

When the game is served through a hosted proxy that cannot preserve websocket query strings (notably the Kubernetes
API server's websocket proxy, which strips them), the platform pre-computes the exact websocket URL it wants the
browser to open and passes that URL as an `address` query parameter on the HTML page.

When `address` is present:

- The client uses `address` directly as the websocket URL, after the same `http`→`ws` / `https`→`wss` protocol
  conversion.
- The client must not merge any other page query params into the websocket URL. Everything the websocket needs is
  already encoded inside `address`; mixing in other page params would corrupt the URL.

When `address` is absent, the default URL derivation applies.

Example:

```text
page URL:       https://stats.example.com/v2/.../proxy/client/player?address=wss%3A%2F%2Fstats.example.com%2F...%2Fproxy%2Fplayer%3Fslot%3D0%26token%3Dabc
websocket URL:  wss://stats.example.com/v2/.../proxy/player?slot=0&token=abc
```

### Replay URI flow

The replay path is a specific instance of the default mechanic. The replay artifact URI travels end-to-end through
the page query string:

1. **Source.** A local CLI prints a URL like
   `http://127.0.0.1:<port>/client/replay?uri=file:///path/to/replay.json`. Hosted Observatory composes
   `https://.../proxy/client/replay?uri=https://.../replay.json.z`.
2. **Browser** opens the page (in a tab locally, or in an iframe in hosted Observatory).
3. The game serves the replay viewer HTML.
4. The JS applies the default derivation: protocol → `ws[s]`, path `/client/replay` → `/replay`, query preserved.
5. The websocket opens at `/replay?uri=<replay-uri>`.
6. The game's `/replay` websocket handler reads `uri` from the websocket's query params and streams replay data
   loaded from that URI.

Every component on the path — game, proxies, browser — must preserve the `uri` query param. Platform proxies forward
the request path and query without inspecting or branching on them.

### Contract summary for game authors

A game container must:

- Serve a small HTML viewer at each `/client/<view>` route.
- Have that viewer's JavaScript implement the default URL derivation above, including the `address` override
  behavior.
- Have the corresponding `/<view>` websocket route read `slot`, `token`, `uri`, and any game-owned params from the
  websocket's query string.

The HTML and JavaScript may be game-styled; only the URL derivation contract is fixed. Reference implementations live
in `examples/paintarena/game/client/` (in this package) and `worlds/cogs_vs_clips/game/client/` (in the repo root).

## Episode Lifecycle

1. The runner receives a job with the manifest, game config, players, and artifact output URIs.
2. The runner generates one token per player slot.
3. The runner writes the concrete game config, including `tokens`.
4. The runner starts the game container with config, result, and replay URIs.
5. The game reads its config and starts listening on port 8080.
6. The runner waits for `GET /healthz` to return 200.
7. The runner starts one player container per slot.
8. Each player gets `COGAMES_ENGINE_WS_URL=ws://<engine-host>/player?slot=<slot>&token=<token>` and,
   optionally, `COGAME_LOG_URI=...` with the same posting contract as the game.
9. Players connect to `/player` and send game-specific actions.
10. Viewers may connect to `/global`.
11. The game runs until the episode ends.
12. The game writes results to `COGAME_RESULTS_URI`.
13. The game writes a replay to `COGAME_SAVE_REPLAY_URI`.
14. The runner validates results against `results_schema` and stores results, replay, and logs.

The final results file must match `game.results_schema`. It must include `scores`, one number per player slot, and may
include extra game-specific fields declared by the schema.

## Certification

Coworld certification turns the manifest's `certification` fixture into one local episode. It runs the game and bundled
player images, checks the HTTP routes, verifies that bad player tokens are rejected, validates final results, and checks
that the replay viewer can start.
