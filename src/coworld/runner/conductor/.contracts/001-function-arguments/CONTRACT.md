---
name: coworld-conductor-function-arguments
message: Prefer named object arguments for multiple, boolean, or optional inputs.
---

# Function arguments

These conventions govern the TypeScript adapter and image builder in this directory. The existing Coworld and Conductor wire formats remain unchanged.

## Rules

- Prefer one object argument for owned functions and constructors with multiple inputs, boolean inputs, or optional inputs.
- Destructure the object in the signature. Keep its options type beside the implementation.
- Keep one required, non-boolean input positional when its meaning is clear at the call site.
- Preserve signatures required by Node, Cloudflare, and other dependencies, including their callbacks.

```typescript
type PrepareFilesOptions = {
  inputPath: string
  scratchDirectory: string
}

async function prepareFiles({ inputPath, scratchDirectory }: PrepareFilesOptions) {
  // Read the input and prepare this attempt's files.
}

await prepareFiles({ inputPath, scratchDirectory })
```

## Checks

Read changed declarations and call sites together. Confirm named fields explain the inputs and external signatures remain compatible.
