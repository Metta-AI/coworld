# Coworld Starter Templates

The game/player scaffolds use Observatory-hosted (`platform-hosted`) container players. New Coworlds may choose
`game-hosted` files instead; read [the runtime decision guide](../docs/PLAYER_RUNTIMES.md) and implement the linked
seats and output contracts. There is no generic game-hosted interpreter or sandbox in these templates.

These templates are shipped inside the `coworld` Python package so a new Coworld can start from the same role shapes the
package validates and documents.

Find the installed template directory with:

```bash
python - <<'PY'
from importlib.resources import files

print(files("coworld") / "templates")
PY
```

Use these templates as starter files, then compare the result with the complete Paint Arena example under
`coworld/examples/paintarena`.

## Start a player project

Run `coworld init player ./my-player`. See
[player project initialization](https://docs.softmax.com/coworld/cli#start-a-player-project) for target requirements,
generated files, runtime limits, and next steps.

## Contents

| Role         | Template path         | Shape                                                                                                               |
| ------------ | --------------------- | ------------------------------------------------------------------------------------------------------------------- |
| Game         | `roles/game/`         | FastAPI game server scaffold with `/healthz`, `/client/*`, `/player`, `/global`, and artifact URI helpers.          |
| Player       | `roles/player/`       | WebSocket player loop scaffold using `COWORLD_PLAYER_WS_URL`.                                                       |
| Commissioner | `roles/commissioner/` | WebSocket commissioner scaffold plus manifest fragment.                                                             |
| Grader       | `roles/grader/`       | One-shot bundle consumer using `COGAME_EPISODE_BUNDLE_URI` and `COGAME_GRADE_URI`.                                  |
| Diagnoser    | `roles/diagnoser/`    | One-shot bundle consumer using `COGAME_EPISODE_BUNDLE_URI`, `COGAME_TARGET_POLICY_URI`, and `COGAME_DIAGNOSIS_URI`. |
| Optimizer    | `roles/optimizer/`    | Optimizer manifest fragment and minimal plan writer for game-specific optimizer experiments.                        |

## Complete Example

Paint Arena is the canonical full example packaged with Coworld. Its single image contains concrete game, player,
grader, diagnoser, and optimizer runnables, plus a manifest template that declares every container role section.

There is no reporter template here: reporters are submittable wasm components (spec 0061), not containers, and the wasm
authoring template ships with the reporter SDK. See `docs/roles/REPORTER.md` for the contract.
