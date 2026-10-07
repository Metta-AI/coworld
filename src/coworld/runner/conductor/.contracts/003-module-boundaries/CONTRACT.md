---
name: coworld-conductor-module-boundaries
message: Keep coherent operations and their state under explicit module boundaries.
---

# Module boundaries

These conventions govern the TypeScript adapter and image builder in this directory. The existing Coworld and Conductor wire formats remain unchanged.

## Rules

- Name modules for their behavior. Avoid generic `utils`, `helpers`, or `common` modules.
- Keep lifecycle state with the operations that maintain it. Extract the complete behavior rather than separate state, event, and cleanup files.
- Keep options and local result types beside their implementation. Shared protocol types describe the wire boundary only.
- Use explicit named exports at intentional folder and package boundaries. Outside consumers use that entry point; implementation imports remain within the owner.
- Keep modules private until another production consumer needs their API. A folder entry point defines visibility, not just a shorter import path.
- Preserve tool-required entry points and export formats. Executable scripts may directly compose sibling modules within their owning folder.
- Add nested folders or packages for a concrete responsibility or dependency boundary. Keep ordinary glue inline.

## Checks

Trace a changed caller through the owning operation. Confirm it does not reach through a public boundary, duplicate lifecycle state, or require a chain of forwarding wrappers.
