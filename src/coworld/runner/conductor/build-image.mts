import { parseArgs } from 'node:util'
import { execFileSync } from 'node:child_process'
import { mkdtemp, copyFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const { values } = parseArgs({
  options: {
    runner: { type: 'string' },
    'adapter-only': { type: 'boolean', default: false },
    'payload-only': { type: 'boolean', default: false },
    'game-image': { type: 'string' },
    tag: { type: 'string' },
  },
})

const modes = [Boolean(values.runner), values['adapter-only'], values['payload-only']]
const requiresGame = !values['payload-only']
const validGame = values['game-image']?.match(/@sha256:[a-f0-9]{64}$/)

if (modes.filter(Boolean).length !== 1 || (requiresGame && !validGame) || !values.tag) {
  throw new Error(
    'Usage: node build-image.mts --payload-only --tag image:local; or ' +
      '(--runner /path/to/server.mjs | --adapter-only) ' +
      '--game-image registry/image@sha256:... --tag image:local'
  )
}

const target = values['payload-only'] ? 'payload' : values['adapter-only'] ? 'adapter' : 'runtime'
const gameArguments = values['game-image']
  ? ['--build-arg', `GAME_IMAGE=${values['game-image']}`]
  : []

const buildDirectory = await mkdtemp(join(tmpdir(), 'coworld-conductor-image-'))
const sourceDirectory = fileURLToPath(new URL('.', import.meta.url))
const adapterFiles = [
  'Dockerfile',
  'episode-files.mts',
  'game-hosted.mts',
  'game-outcome.mts',
  'game-process.mts',
  'protocol.mts',
]

try {
  if (values.runner) {
    await copyFile(resolve(values.runner), join(buildDirectory, 'server.mjs'))
  }

  await copyFile(
    join(sourceDirectory, 'release/runtime.json'),
    join(buildDirectory, 'runtime.json')
  )
  await copyFile(
    join(sourceDirectory, 'release/smoke-adapter.mts'),
    join(buildDirectory, 'smoke-adapter.mts')
  )

  for (const name of adapterFiles) {
    await copyFile(join(sourceDirectory, name), join(buildDirectory, name))
  }

  execFileSync(
    'docker',
    [
      'build',
      '--target',
      target,
      '--platform',
      'linux/amd64',
      ...gameArguments,
      '--tag',
      values.tag,
      buildDirectory,
    ],
    { stdio: 'inherit' }
  )

  execFileSync('docker', ['image', 'inspect', values.tag, '--format', '{{.Id}}'], {
    stdio: 'inherit',
  })
} finally {
  await rm(buildDirectory, { recursive: true, force: true })
}
