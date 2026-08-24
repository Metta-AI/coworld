# Platform Ladder Seating

How the platform ladder (`league.settings.ladder.scheduler`) deals entrants onto a game's seats. Seat index `s` below
is the game's own 0-based slot order — the same index the game uses for its player protocol, teams, and scoring. If
your game has internal team structure, check the formula for your league's strategy against your game's slot→team map
**before** requesting a seed: a mismatch does not error, it silently plays a different game.

## Per-strategy slot→entrant formulas

| Strategy | Seats hold | Slot→entrant formula |
| --- | --- | --- |
| `round_robin`, `balanced_rotation`, `swiss_neighbor`, `random_fill` | Distinct entrants | Each seat holds a different entrant; seat order carries no team meaning. Use these for FFA-shaped games only. |
| `team_pair` (default `team_layout: "interleaved"`) | 2 captains, cloned | Seat `s` → captain `s % 2` (team of seat `s` is its parity); with `team_layout: "blocks"`, seat `s` → captain `s // (seat_count / 2)` (contiguous halves). Even seat count required; each unordered pair plays both side assignments. |
| `team_n` (default `team_layout: "interleaved"`) | `team_count` champions, cloned | Seat `s` → champion `s % team_count` (team of seat `s` is `s % team_count`). A champion's seats are `{t, t + team_count, t + 2·team_count, …}`. |
| `team_n` with `team_layout: "blocks"` | `team_count` champions, cloned | `team_size = seat_count / team_count`; seat `s` → champion `s // team_size` (team of seat `s` is `s // team_size`). A champion's seats are the contiguous run `[t·team_size, (t+1)·team_size)`. |
| `variable_seat`, `scaling_roster` | Distinct entrants | As the FFA strategies, with a per-episode seat count (sampled range / largest fitting rung). |
| `clone_fill` | 1 champion | Every seat of the episode holds the same champion. |

Additional `team_n` mechanics:

- **Matchups.** Each episode seats `team_count` distinct champions (an "assignment"), drawn by enumeration or sampling;
  `allied_teams` declares which of the `team_count` seat-groups alias into the same real side, and the concrete
  side arrangement is drawn per episode.
- **`variant_rotation`.** A rotated variant may seat any multiple of `team_count`; the episode's champion assignment is
  re-dealt at that variant's seat count with the **same** `team_layout` geometry, so every rotated variant must map
  slots to teams the same way.
- **Insufficient players.** Below `team_count` live entrants, `insufficient_players` either skips the round
  (`do_not_run`) or pads the assignment (`filler_policy` / `multiple_seats`) and emits a single episode.

Under `team_pair` and `team_n` (and for `insufficient_players` pad seats), clone and pad seats are **filler-marked**:
every seat except the first occurrence of each real entrant is recorded as filler, so each entrant is credited once per
episode regardless of how many seats it fields. `clone_fill` is the exception — nothing is filler-marked; **every**
seat of its self-play episodes is credited and folded into one score per `clone_score_aggregation` (`mean`/`sum`).

## Seed policies

When a league sets `seed_policy_number` K > 0 and a seed-policy pool, FFA strategies
(`round_robin`, `balanced_rotation`, `swiss_neighbor`, `random_fill`) plan against
**N−K** ranked seats, then append K seats sampled from the pool (shuffle then cycle).
Those K seats are both `filler_seats` and `seed_seats` — they never count toward
rankings. Remaining shortfall among the ranked seats still uses `insufficient_players`.
Team / `clone_fill` / variable / scaling strategies reject K > 0.

## Worked example: contiguous team pairs

A 16-seat game defining 8 teams as contiguous slot pairs (`team = slot div 2`) under `team_n` with `team_count: 8`:

- **Interleaved (default):** entrant `t` receives seats `{t, t + 8}` — which the game maps to two *different* teams
  (`t div 2` and `t div 2 + 4`). Every entrant straddles two teams and every team mixes two entrants: silently a
  different game.
- **Blocks:** entrant `t` receives seats `{2t, 2t + 1}` — exactly the game's team `t`.

A game already implemented against interleaved seating (e.g. via an external↔internal seat adapter at the game
boundary) should keep the interleaved default; `team_layout` describes how the platform deals seats, and changing it
under an adapter double-transforms the mapping.
