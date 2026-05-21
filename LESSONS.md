# Lessons

Durable coding-agent and codebase guidance distilled from merged work. Keep entries short, current, and useful for
future changes in this area.

## 2026-05-21

- Reporter reference PRs should add separate manifest role entries and dependencies without taking ownership of sibling
  reporter branches. (PR #13793)
- Coworld role manifest changes must update role docs, templates, schemas, certifier and bundle tests, and replay-viewer
  typing together. (PR #13810)
- When a generated Kubernetes client gets 401 with valid RBAC, compare its emitted Authorization header against a raw
  in-pod request before changing cluster permissions. (PR #13845)
- Kubernetes runner auth fixes must be verified inside the deployed image and client version; check generated client
  auth_settings before changing RBAC or tokens. (PR #13847)
- Coworld manifest template changes should move role sections, canonical world templates, schema files, docs, certifier
  checks, and upload substitution together. (PRs #13744, #13747, #13778)
- Coworld runner image changes should verify source-change build triggers, image architecture, dependency pins,
  transient artifact-upload retries, and the actual image tag used by tournament jobs. (PRs #13454, #13455, #13456)
- Local `coworld play` work should exercise the real compose config, generated episode request, artifact workspace,
  local player networking, and replay-mode output before updating docs. (PRs #13478, #13775, #13868)
- Replay runtime fixes should keep routing backend-owned, preserve replay query parameters, verify readiness before
  viewer URLs, and pin runtime identity to the recorded episode. (PRs #13300, #13317, #13736, #13760)
- Policy/player contracts need explicit failure behavior: bounded tick waits, valid rejection closes, unique replay
  player names, and fail-fast crashed player pods. (PRs #13356, #13399, #13453)
- Public Coworld package docs should point at public package repos and installed package entrypoints, not private Metta
  internal paths or stale starter-manifest locations. (PRs #13386, #13449, #13557)
