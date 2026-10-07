import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { mkdtemp, readFile, rm, writeFile, stat } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const { command, smoke } = JSON.parse(await readFile('/opt/worlds/runtime.json', 'utf8'))
const directory = await mkdtemp(join(tmpdir(), 'gota-qualification-'))

try {
  const policies = []

  for (const policy of smoke.policies) {
    const path = join(directory, `${policy.role}.bas`)
    await writeFile(path, policy.source)
    policies.push({ role: policy.role, format: policy.format, path })
  }

  const inputPath = join(directory, 'input.json')
  const outputPath = join(directory, 'output.json')
  const input = {
    protocol: 1,
    seed: smoke.seed,
    config: smoke.config,
    deadlineAt: Date.now() + smoke.timeoutMs,
    policies,
  }

  await writeFile(inputPath, JSON.stringify(input))
  execFileSync(command[0], command.slice(1), {
    env: {
      PATH: '/usr/local/bin:/usr/bin:/bin',
      WORLD_INPUT_PATH: inputPath,
      WORLD_OUTPUT_PATH: outputPath,
      WORLD_SCRATCH_PATH: directory,
    },
    timeout: smoke.timeoutMs + 5000,
    stdio: 'inherit',
  })

  const output = JSON.parse(await readFile(outputPath, 'utf8'))
  assert.equal(output.result.kind, 'completed')
  assert.equal(output.result.result.scores.length, smoke.policies.length)
  assert.ok((await stat(join(directory, 'replay.replay'))).size > 0)
  console.log('Pinned GOTA adapter produced scores and a replay without network access.')
} finally {
  await rm(directory, { recursive: true, force: true })
}
