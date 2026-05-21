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
