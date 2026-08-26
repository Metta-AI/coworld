# Bracket Tournaments

A league can run **bracket tournaments** on top of its ladder: a frozen roster of entrants seeded into a
double-elimination bracket, executed wave by wave, ending in recorded placements. Tournaments are platform objects
(`tour_<uuid>`) served by the Observatory v2 API; this page documents the objects and the read paths a Coworld tool or
agent needs. The ops-oriented map (endpoints table, gotchas, how the mainroom display consumes them) lives in
[`docs/ai/onboarding/services/coworlds/tournaments.md`](../../../../../docs/ai/onboarding/services/coworlds/tournaments.md).

Naming note: the `coworld` CLI's `tournament_cli.py` commands (`leagues`, `divisions`, `rounds`, `results`,
`memberships`, `xp-request`, …) predate bracket tournaments and cover the **ladder** objects. There are no bracket CLI
commands yet; use the HTTP API below.

## Objects

**TournamentSummary** — list row from `GET /v2/leagues/{league_id}/tournaments`: `tournament_id`, `league_id`, `name`,
`status` (`draft | locked | running | completed | cancelled | failed`), `created_at`, `locked_at`, `started_at`,
`completed_at`, `error`.

**TournamentPublic** — full row from `GET /v2/tournaments/{tournament_id}`, adds:

- `definition` — the frozen config:
  - `schedule`: `{mode: "on_demand" | "scheduled", starts_at?, ends_at?}`
  - `roster_generator` (discriminated on `type`): `explicit` (`entrants` + `host_division_id`), `top_n` (`division_id`,
    `n`), or `division_all` (`division_id`)
  - `round_generator`: `{strategy: "double_elimination", grand_final_reset: bool, best_of: 1..15}`
  - `placements`: `{type: "bracket_finish", tiers: [{name, ranks: [lo, hi]}]}`
- `frozen_entrants` — roster snapshot taken at `:lock`: `entrant_id` (`ent-N`), `player_id`, `policy_version_id`, `seed`
  (**0-based**), `display_name`, `league_policy_membership_id`.
- `visualization` — the bracket, discriminated on `strategy` (only `double_elimination` today): `size`,
  `grand_final_reset`, `entrants` (as above minus membership), `matches`, `current_round_key`, `highlight_match_ids`,
  `champion_entrant_id`.
- `wave_experience_request_ids` — `{"wave-0": "xreq_…", "wave-1": "xreq_…", …}`; each wave of bracket matches runs as
  one Experience Request.
- `placements` — final results: `entrant_id`, `player_id`, `rank`, optional `tier` name, optional `score`.
- `host_division_id`, `locked_by`, `requester_user_id`, `idempotency_key`, timestamps, `error`.

**BracketMatchView** (inside `visualization.matches`) — `match_id` encodes bracket position: `wb-<round>-<slot>`
(winners bracket), `lb-<round>-<slot>` (losers), `gf-0` (grand final). Fields: `bracket`
(`winners | losers | grand_final`), `round_index`, `slot_index`, `label` (e.g. "Winners Round 1 · Match 7"),
`series_format` (`bo1`…`bo15`), `entrant_a_id`, `entrant_b_id`, `winner_entrant_id`, `status`
(`pending | ready | running | completed | void`), and `edges`
(`{to_match_id, slot: a|b, kind: advance|drop|grand_final}`).

Bracket structure exists **only** in the tournament row (`visualization` / `structure_state`); episodes and rounds have
no `bracket_id` column.

## Reading a tournament's episodes

```
GET /v2/leagues/{league_id}/tournaments            -> choose a tournament
GET /v2/tournaments/{tour_…}                       -> wave_experience_request_ids, visualization
GET /v2/experience-requests/{xreq_…}/episodes      -> ereq_ rows: status, replay_url, episode_id,
                                                      coworld_id, participants (player ids), scores
```

Attribute an episode to its bracket match by matching participant `player_id`s to the match's entrant pair through
`visualization.entrants`. The same two players can meet more than once across a bracket (a winners match, then a losers
or grand-final rematch) — disambiguate by match `status`/`round_index`.

Wave episodes carry `episode_tags: {source: "tournament", tournament_id, round_key, experience_request_id}`. Read one
wave through `GET /v2/experience-requests/{xreq}/episode-requests`. All `best_of` games of a series are materialized
when the wave dispatches, so a decided series may still play out its remaining games.

## Lifecycle (writes)

`draft` (create via `POST /v2/leagues/{league_id}/tournaments`, edit via `PATCH`) → `:lock` (freezes roster/definition)
→ `:start` (enqueues the Temporal `TournamentWorkflow`) → `running` → `completed` (placements recorded). `:cancel` and
`:fail` are terminal; `:advance` advances bracket state. The `:prepare-wave` / `:dispatch-wave` / `:cancel-wave` verbs
are the workflow's own machinery (PLATFORM_WORKER-gated) — don't call them by hand.
