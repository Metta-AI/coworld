import { createHash, randomBytes } from 'node:crypto'
import { readFile, stat, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'

export async function prepareGameFiles(input, directory) {
  const uri = (name) => pathToFileURL(join(directory, name)).href
  const policies = [...input.policies].sort((left, right) => Number(left.role.slice(5)) - Number(right.role.slice(5)))
  const seats = []
  for (const [slot, policy] of policies.entries()) {
    if (policy.role !== `seat-${slot}`) throw new Error('Roles must be contiguous seat-0, seat-1, ...')
    const bytes = await readFile(policy.path)
    seats.push({
      slot,
      file_uri: pathToFileURL(policy.path).href,
      size_bytes: bytes.length,
      content_hash: `sha256:${createHash('sha256').update(bytes).digest('hex')}`,
      log_uri: uri(`seat-${slot}.log`),
      artifact_uri: uri(`seat-${slot}.zip`),
    })
  }
  if (!Array.isArray(input.config.players) || input.config.players.length !== seats.length) {
    throw new Error('Game configuration must contain one resolved player per seat')
  }
  const config = {
    ...input.config,
    seed: input.seed,
    tokens: seats.map(() => randomBytes(16).toString('base64url')),
  }
  await writeFile(join(directory, 'config.json'), JSON.stringify(config))
  await writeFile(
    join(directory, 'seats.json'),
    JSON.stringify({ schema: 'coworld-player-seats/1', seats, player_status_uri: uri('player-status.json') })
  )
  return {
    COGAME_CONFIG_URI: uri('config.json'),
    COGAME_PLAYER_SEATS_URI: uri('seats.json'),
    COGAME_RESULTS_URI: uri('results.json'),
    COGAME_SAVE_REPLAY_URI: uri('replay.replay'),
    COGAME_PLAYER_FAILURE_URI: uri('failure.json'),
  }
}

export class GameMarkerError extends Error {}

export async function readMarker(directory, name) {
  try {
    const path = join(directory, name)
    const metadata = await stat(path)
    if (!metadata.isFile() || metadata.size > 100_000) {
      throw new GameMarkerError(`${name} must be a regular file of at most 100,000 bytes`)
    }
    return JSON.parse(await readFile(path, 'utf8'))
  } catch (error) {
    // Games may create a marker before finishing its JSON write.
    if (error.code === 'ENOENT' || error instanceof SyntaxError) return undefined
    throw error
  }
}

export async function replayExists(directory) {
  try {
    return (await stat(join(directory, 'replay.replay'))).isFile()
  } catch (error) {
    if (error.code === 'ENOENT') return false
    throw error
  }
}
