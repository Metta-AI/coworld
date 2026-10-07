import { spawn } from 'node:child_process'
import { readFile, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { setTimeout as delay } from 'node:timers/promises'
import { GameMarkerError, prepareGameFiles } from './files.mjs'
import { readOutcome } from './outcomes.mjs'

// Conductor validates its process input. Metta validates the game configuration before submission.
const input = JSON.parse(await readFile(process.env.WORLD_INPUT_PATH, 'utf8'))
if (input.protocol !== 1) throw new Error('Unsupported Conductor protocol')
const directory = process.env.WORLD_SCRATCH_PATH
const gameFiles = await prepareGameFiles(input, directory)
const [executable, ...args] = process.argv.slice(2)
if (!executable) throw new Error('An operator-installed game executable is required')
const child = spawn(executable, args, {
  stdio: ['ignore', 'pipe', 'pipe'],
  cwd: directory,
  env: {
    PATH: '/usr/local/bin:/usr/bin:/bin',
    HOME: directory,
    TMPDIR: directory,
    COGAME_HOST: '127.0.0.1',
    COGAME_PORT: '8081',
    ...gameFiles,
  },
})
let diagnosticBytes = Buffer.alloc(0)
for (const stream of [child.stdout, child.stderr]) {
  stream.on('data', (chunk) => {
    diagnosticBytes = Buffer.concat([diagnosticBytes, chunk]).subarray(-64 * 1024)
  })
}
let exited = false
let launchError
const closed = new Promise((resolve) => {
  child.once('error', (error) => {
    launchError = error
    exited = true
    resolve()
  })
  child.once('close', () => {
    exited = true
    resolve()
  })
})
let outcome
try {
  while (Date.now() < input.deadlineAt) {
    if (launchError) {
      outcome = { kind: 'failed', errorType: 'game_error', message: 'Installed game executable could not start' }
      diagnosticBytes = Buffer.from(String(launchError))
      break
    }
    try {
      outcome = await readOutcome(directory, input.policies.length)
    } catch (error) {
      if (!(error instanceof GameMarkerError)) throw error
      outcome = { kind: 'failed', errorType: 'game_error', message: error.message }
    }
    const processFailed = (child.exitCode !== null && child.exitCode !== 0) || child.signalCode !== null
    if (processFailed && outcome?.kind !== 'failed') {
      outcome = {
        kind: 'failed',
        errorType: 'game_error',
        message: 'Game process failed before completing the episode',
      }
    }
    if (outcome) break
    if (exited) {
      outcome = { kind: 'failed', errorType: 'game_error', message: 'Game exited before completing artifacts' }
      break
    }
    await delay(10)
  }
  if (!outcome) {
    outcome = { kind: 'failed', errorType: 'episode_timeout', message: 'Game exceeded its deadline' }
  }
} finally {
  child.kill('SIGTERM')
  await Promise.race([closed, delay(1000, undefined, { ref: false })])
  if (!exited) {
    child.kill('SIGKILL')
    await closed
  }
}
await writeFile(join(directory, 'diagnostics.log'), diagnosticBytes)
const artifacts = [{ name: 'diagnostics', path: 'diagnostics.log', mediaType: 'text/plain' }]
if (outcome.kind === 'completed') {
  artifacts.push(
    { name: 'results', path: 'results.json', mediaType: 'application/json' },
    { name: 'replay', path: 'replay.replay', mediaType: 'application/octet-stream' }
  )
}
await writeFile(process.env.WORLD_OUTPUT_PATH, JSON.stringify({ result: outcome, artifacts }))
