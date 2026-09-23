# Platform Ladder Seating

How the platform ladder (`league.settings.ladder.scheduler`) deals entrants onto a game's seats. Seat index `s` below is
the game's own 0-based slot order — the same index the game uses for its player protocol, teams, and scoring. If your
game has internal team structure, check the formula for your league's strategy against your game's slot→team map
**before** requesting a seed: a mismatch does not error, it silently plays a different game.

## Per-strategy slot→entrant formulas

| Strategy                                                            | Seats hold                     | Slot→entrant formula                                                                                                                                                                                                                                              |
| ------------------------------------------------------------------- | ------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `round_robin`, `balanced_rotation`, `swiss_neighbor`, `random_fill` | Distinct entrants              | Each seat holds a different entrant; seat order carries no team meaning. Use these for FFA-shaped games only.                                                                                                                                                     |
| `team_pair` (default `team_layout: "interleaved"`)                  | 2 captains, cloned             | Seat `s` → captain `s % 2` (team of seat `s` is its parity); with `team_layout: "blocks"`, seat `s` → captain `s // (seat_count / 2)` (contiguous halves). Even seat count required; exhaustive pairs play both sides, while a participation floor samples pairs. |
| `team_n` (default `team_layout: "interleaved"`)                     | `team_count` champions, cloned | Seat `s` → champion `s % team_count` (team of seat `s` is `s % team_count`). A champion's seats are `{t, t + team_count, t + 2·team_count, …}`.                                                                                                                   |
| `team_n` with `team_layout: "blocks"`                               | `team_count` champions, cloned | `team_size = seat_count / team_count`; seat `s` → champion `s // team_size` (team of seat `s` is `s // team_size`). A champion's seats are the contiguous run `[t·team_size, (t+1)·team_size)`.                                                                   |
| `variable_seat`, `scaling_roster`                                   | Distinct entrants              | As the FFA strategies, with a per-episode seat count (sampled range / largest fitting rung or rotating rung). When rotating rungs, extra entrants are sampled and short tables use marked filler seats.                                                           |
| `clone_fill`                                                        | 1 champion                     | Every seat of the episode holds the same champion.                                                                                                                                                                                                                |

## Participant selection

For routine play, use `balanced_rotation` with `min_episodes_per_entrant`, or set `num_episodes` for a fixed budget.
Participation sampling prioritizes entrants with fewer appearances and breaks ties randomly. It mixes lineups between
matches and randomizes equivalent seats. A participation floor stops once everyone has played enough. Nearby-skill
matching may need extra matches to cover isolated players. Budget and floor settings are mutually exclusive.
`random_fill` also supports either count setting. Reserve `round_robin` for deliberate exhaustive evaluations.

Set `matchmaking: "elo_softmax"` on `balanced_rotation`, `random_fill`, `team_pair`, or `team_n` to prefer opponents
near the selected player's rating. Set either a budget or participation floor; `team_pair` supports the floor only.
`matchmaking_temperature` controls how widely ratings can differ: smaller values prefer closer opponents.
`swiss_neighbor` chooses neighbors by current standing and randomizes ties. Elo leagues use Elo points; score leagues
use their raw score standings, with the configured maximize/minimize direction. New entrants use the configured initial
rating or standing. The Swiss sampler's default distance scale is 100 standing units; explicit `matchmaking_temperature`
remains an Elo-point scale for `elo_softmax`.

## Team ownership

With `distinct_teammates: true`, `team_n` selects a full lobby of different entrants before assigning teams.
Nearby-rating selection applies to the whole lobby. It balances team rating totals and randomizes team sides and each
team's seats. No player has a reserved team or game slot. The game must map seats to teams according to `team_layout`.

Without distinct teammates, one entrant controls every seat in its assigned team. `allied_teams` groups teams into real
sides; side assignments change between matches while those groups retain their game-defined meaning.

A `team_n` variant rotation may contain different seat counts, each divisible by `team_count` and using the same team
layout. Distinct-player lobbies are selected for each variant's actual size. Under `do_not_run`, the scheduler waits for
enough distinct entrants to fill the largest rotated variant. Clone teams need only `team_count` entrants.
`filler_policy` and `multiple_seats` explicitly allow padding short rosters.

Under `team_pair` and `team_n` (and for `insufficient_players` pad seats), clone and pad seats are **filler-marked**:
every seat except the first occurrence of each real entrant is recorded as filler, so each entrant is credited once per
episode regardless of how many seats it fields. `clone_fill` is the exception — nothing is filler-marked; **every** seat
of its self-play episodes is credited and folded into one score per `clone_score_aggregation` (`mean`/`sum`).

## Seed policies

When a league sets `seed_policy_number` K > 0 and a seed-policy pool, FFA strategies (`round_robin`,
`balanced_rotation`, `swiss_neighbor`, `random_fill`) plan against **N−K** ranked seats, then add K seats sampled from
the pool (shuffle then cycle). Final seat order is randomized, including seed seats. Those K seats are both
`filler_seats` and `seed_seats` — they never count toward rankings. Remaining shortfall among the ranked seats still
uses `insufficient_players`. Team / `clone_fill` / variable / scaling strategies reject K > 0.

## Worked example: contiguous team pairs

A 16-seat game defining 8 teams as contiguous slot pairs (`team = slot div 2`) under `team_n` with `team_count: 8`:

- **Interleaved (default):** entrant `t` receives seats `{t, t + 8}` — which the game maps to two _different_ teams
  (`t div 2` and `t div 2 + 4`). Every entrant straddles two teams and every team mixes two entrants: silently a
  different game.
- **Blocks:** entrant `t` receives seats `{2t, 2t + 1}` — exactly the game's team `t`.

A game already implemented against interleaved seating (e.g. via an external↔internal seat adapter at the game boundary)
should keep the interleaved default; `team_layout` describes how the platform deals seats, and changing it under an
adapter double-transforms the mapping.
