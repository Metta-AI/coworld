import { createHash, randomBytes } from 'node:crypto'
import { readFile, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
import type { GameOutcome, OutputArtifact, ProcessInput } from './protocol.mts'

type PrepareGameFilesOptions = {
  processInput: ProcessInput
  scratchDirectory: string
}

export async function prepareGameFiles({
  processInput,
  scratchDirectory,
}: PrepareGameFilesOptions): Promise<Record<string, string>> {
  const fileUri = (name: string) => pathToFileURL(join(scratchDirectory, name)).href
  const policiesBySeat = [...processInput.policies].sort((left, right) => {
    const leftSeat = Number(left.role.slice(5))
    const rightSeat = Number(right.role.slice(5))

    return leftSeat - rightSeat
  })

  const seats = []

  for (const [slot, policy] of policiesBySeat.entries()) {
    if (policy.role !== `seat-${slot}`) {
      throw new Error('Roles must be contiguous seat-0, seat-1, ...')
    }

    const policyBytes = await readFile(policy.path)
    const policyDigest = createHash('sha256').update(policyBytes).digest('hex')

    seats.push({
      slot,
      file_uri: pathToFileURL(policy.path).href,
      size_bytes: policyBytes.length,
      content_hash: `sha256:${policyDigest}`,
      log_uri: fileUri(`seat-${slot}.log`),
      artifact_uri: fileUri(`seat-${slot}.zip`),
      annotations_uri: fileUri(`seat-${slot}.annotations.jsonl`),
    })
  }

  const resolvedPlayers = processInput.config.players

  if (!Array.isArray(resolvedPlayers) || resolvedPlayers.length !== seats.length) {
    throw new Error('Game configuration must contain one resolved player per seat')
  }

  const gameConfig = {
    ...processInput.config,
    seed: processInput.seed,
    tokens: seats.map(() => randomBytes(16).toString('base64url')),
  }

  const playerSeats = {
    schema: 'coworld-player-seats/2',
    seats,
    player_status_uri: fileUri('player-status.json'),
  }

  await writeFile(join(scratchDirectory, 'config.json'), JSON.stringify(gameConfig))
  await writeFile(join(scratchDirectory, 'seats.json'), JSON.stringify(playerSeats))

  return {
    COGAME_CONFIG_URI: fileUri('config.json'),
    COGAME_PLAYER_SEATS_URI: fileUri('seats.json'),
    COGAME_RESULTS_URI: fileUri('results.json'),
    COGAME_SAVE_REPLAY_URI: fileUri('replay.replay'),
    COGAME_PLAYER_FAILURE_URI: fileUri('failure.json'),
  }
}

type WriteEpisodeOutputOptions = {
  outputPath: string
  scratchDirectory: string
  outcome: GameOutcome
  diagnostics: Buffer
}

export async function writeEpisodeOutput({
  outputPath,
  scratchDirectory,
  outcome,
  diagnostics,
}: WriteEpisodeOutputOptions): Promise<void> {
  const diagnosticsPath = join(scratchDirectory, 'diagnostics.log')

  await writeFile(diagnosticsPath, diagnostics)

  const artifacts: OutputArtifact[] = [
    {
      name: 'diagnostics',
      path: 'diagnostics.log',
      mediaType: 'text/plain',
    },
  ]

  if (outcome.kind === 'completed') {
    artifacts.push(
      {
        name: 'results',
        path: 'results.json',
        mediaType: 'application/json',
      },
      {
        name: 'replay',
        path: 'replay.replay',
        mediaType: 'application/octet-stream',
      }
    )
  }

  const processOutput = {
    result: outcome,
    artifacts,
  }

  await writeFile(outputPath, JSON.stringify(processOutput))
}
