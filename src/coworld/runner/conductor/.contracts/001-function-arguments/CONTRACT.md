---
name: coworld-conductor-function-arguments
message: Use one named object argument for multiple, boolean, or optional inputs; keep externally defined signatures.
---

## Rules

Give an owned function or constructor with more than one input a single object argument with named fields.
Use an object argument when any input is a boolean, is optional, or has a default.
Allow one required, non-boolean input to stay positional when its meaning is clear at the call site.
Destructure the object argument in the signature.
Pass an existing domain object directly instead of wrapping it in a redundant options object.

Export an options type only when another module needs to name it.
Name each boolean field for the behavior it enables, such as `includeArchived`, never a generic `flag` or `mode`.
Use a discriminated union when combinations of options would otherwise allow invalid states.
Keep required fields required; do not add defaults that hide missing caller input.
Use named fields for callbacks the code defines when they report several independent values.

Preserve signatures defined by the language, the runtime, frameworks, and other dependencies, including their callbacks and entry points.
Do not wrap an external function or callback only to convert its positional arguments into an object.

## Checks

Read changed declarations and their call sites together, and confirm each call names its inputs where these rules require it.
For each positional exception, identify the single clear input or the external API that fixes the signature.
Run the type check for the owning package and for affected consumers after a signature change.
Search the change for wrappers whose only job is converting positional arguments into an object.

## Local adaptations

These conventions govern the TypeScript adapter and image builder in this directory.
The existing Coworld and Conductor wire formats remain unchanged.

Preserve signatures required by Node and Cloudflare, including their callbacks.
