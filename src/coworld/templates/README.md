# Coworld Starter Templates

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

## Contents

| Role | Template path | Shape |
| ---- | ------------- | ----- |
| Game | `roles/game/` | FastAPI game server scaffold with `/healthz`, `/client/*`, `/player`, `/global`, and artifact URI helpers. |
| Player | `roles/player/` | WebSocket player loop scaffold using `COWORLD_PLAYER_WS_URL`. |
| Commissioner | `roles/commissioner/` | WebSocket commissioner scaffold plus manifest fragment. |
| Grader | `roles/grader/` | One-shot bundle consumer using `COGAME_EPISODE_BUNDLE_URI` and `COGAME_GRADE_URI`. |
| Diagnoser | `roles/diagnoser/` | One-shot bundle consumer using `COGAME_EPISODE_BUNDLE_URI`, `COGAME_TARGET_POLICY_URI`, and `COGAME_DIAGNOSIS_URI`. |
| Optimizer | `roles/optimizer/` | Optimizer manifest fragment and minimal plan writer for game-specific optimizer experiments. |

## Complete Example

Paint Arena is the canonical full example packaged with Coworld. Its single image contains concrete game, player,
grader, diagnoser, and optimizer runnables, plus a manifest template that declares every container role section.

There is no reporter template here: reporters are submittable wasm components (spec 0061), not containers, and the
wasm authoring template ships with the reporter SDK. See `docs/roles/REPORTER.md` for the contract.
