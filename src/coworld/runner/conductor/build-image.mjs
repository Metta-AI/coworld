import { parseArgs } from 'node:util'
import { execFileSync } from 'node:child_process'
import { mkdtemp, copyFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const { values } = parseArgs({
  options: {
    runner: { type: 'string' },
    'game-image': { type: 'string' },
    tag: { type: 'string' },
  },
})
if (!values.runner || !values['game-image']?.match(/@sha256:[a-f0-9]{64}$/) || !values.tag) {
  throw new Error(
    'Usage: node build-image.mjs --runner /path/to/server.mjs --game-image registry/image@sha256:... --tag image:local'
  )
}
const directory = await mkdtemp(join(tmpdir(), 'coworld-conductor-image-'))
const source = fileURLToPath(new URL('.', import.meta.url))
try {
  await copyFile(resolve(values.runner), join(directory, 'server.mjs'))
  for (const name of ['Dockerfile', 'game-hosted.mjs', 'files.mjs', 'outcomes.mjs'])
    await copyFile(join(source, name), join(directory, name))
  execFileSync(
    'docker',
    [
      'build',
      '--platform',
      'linux/amd64',
      '--build-arg',
      `GAME_IMAGE=${values['game-image']}`,
      '--tag',
      values.tag,
      directory,
    ],
    { stdio: 'inherit' }
  )
  execFileSync('docker', ['image', 'inspect', values.tag, '--format', '{{.Id}}'], {
    stdio: 'inherit',
  })
} finally {
  await rm(directory, { recursive: true, force: true })
}
