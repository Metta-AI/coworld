# Commissioner Role

**Deprecated.** Softmax leagues use the platform ladder (`commissioner_key=platform`) and do
**not** ship a commissioner Docker image or `manifest.commissioner[]`.

| Need | Doc |
| --- | --- |
| Create / maintain a league | [`platform-ladder-league.md`](../../../../../../docs/ai/onboarding/services/coworlds/platform-ladder-league.md) |
| Cut a container league over | [`migrate-to-platform-commissioner.md`](../../../../../../docs/ai/onboarding/services/coworlds/migrate-to-platform-commissioner.md) |
| Delete the container path | [`retire-container-commissioners.md`](../../../../../../docs/ai/onboarding/services/coworlds/retire-container-commissioners.md) |
| Remaining WebSocket message models | [`commissioner/protocol.py`](../../commissioner/protocol.py) |

New Coworlds omit `manifest.commissioner[]`. Do not scaffold a commissioner image, bake a
`ruleset_strategy` YAML into Docker, or use `ux.commissioner` for greenfield leagues.
