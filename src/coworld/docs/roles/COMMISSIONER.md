# Commissioner Role

**Deprecated.** Softmax leagues use the platform ladder (`commissioner_key=platform`) and do
**not** ship a commissioner Docker image or `manifest.commissioner[]`.

| Need | Doc |
| --- | --- |
| Create / maintain a league | [PLATFORM_LADDER_LEAGUE.md](../PLATFORM_LADDER_LEAGUE.md) |
| Cut a container league over | [MIGRATE_TO_PLATFORM_COMMISSIONER.md](../MIGRATE_TO_PLATFORM_COMMISSIONER.md) |
| Remaining WebSocket message models | [`commissioner/protocol.py`](../../commissioner/protocol.py) |

Public git links (after child-repo sync):

- https://github.com/Metta-AI/coworld/blob/main/src/coworld/docs/PLATFORM_LADDER_LEAGUE.md
- https://github.com/Metta-AI/coworld/blob/main/src/coworld/docs/MIGRATE_TO_PLATFORM_COMMISSIONER.md

New Coworlds omit `manifest.commissioner[]`. Do not scaffold a commissioner image, bake a
`ruleset_strategy` YAML into Docker, or use `ux.commissioner` for greenfield leagues.
