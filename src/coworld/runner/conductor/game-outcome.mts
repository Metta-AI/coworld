import { readFile, stat } from 'node:fs/promises'
import { join } from 'node:path'
import { setTimeout as delay } from 'node:timers/promises'
import type { GameProcess } from './game-process.mts'
import type { GameOutcome } from './protocol.mts'

const pollIntervalMs = 10
const maximumMarkerBytes = 100_000
const maximumFailureMessageLength = 2000

type ReadOutcomeOptions = {
  scratchDirectory: string
  playerCount: number
}

type WaitForGameOutcomeOptions = ReadOutcomeOptions & {
  gameProcess: GameProcess
  deadlineAt: number
}

class GameMarkerError extends Error {}

export async function waitForGameOutcome({
  gameProcess,
  scratchDirectory,
  deadlineAt,
  playerCount,
}: WaitForGameOutcomeOptions): Promise<GameOutcome> {
  while (Date.now() < deadlineAt) {
    if (gameProcess.status === 'launch_failed') {
      return {
        kind: 'failed',
        errorType: 'game_error',
        message: 'Installed game executable could not start',
      }
    }

    let outcome: GameOutcome | undefined

    try {
      outcome = await readOutcome({ scratchDirectory, playerCount })
    } catch (error) {
      if (!(error instanceof GameMarkerError)) {
        throw error
      }

      outcome = {
        kind: 'failed',
        errorType: 'game_error',
        message: error.message,
      }
    }

    if (gameProcess.status === 'process_failed' && outcome?.kind !== 'failed') {
      return {
        kind: 'failed',
        errorType: 'game_error',
        message: 'Game process failed before completing the episode',
      }
    }

    if (outcome) {
      return outcome
    }

    if (gameProcess.status === 'exited') {
      return {
        kind: 'failed',
        errorType: 'game_error',
        message: 'Game exited before completing artifacts',
      }
    }

    await delay(pollIntervalMs)
  }

  return {
    kind: 'failed',
    errorType: 'episode_timeout',
    message: 'Game exceeded its deadline',
  }
}

export async function readOutcome({
  scratchDirectory,
  playerCount,
}: ReadOutcomeOptions): Promise<GameOutcome | undefined> {
  const result = await readMarker(join(scratchDirectory, 'results.json'))

  // Complete artifacts take precedence over a failure marker, as in the existing Coworld runner.
  if (result && (await replayExists(scratchDirectory))) {
    const scores = isRecord(result) ? result.scores : undefined
    const hasValidScores =
      Array.isArray(scores) && scores.length === playerCount && scores.every(Number.isFinite)

    if (!isRecord(result) || !hasValidScores) {
      return {
        kind: 'failed',
        errorType: 'results_malformed',
        message: 'Invalid per-seat scores',
      }
    }

    return {
      kind: 'completed',
      result,
    }
  }

  const failure = await readMarker(join(scratchDirectory, 'failure.json'))

  if (!failure) {
    return undefined
  }

  const message = isRecord(failure) ? failure.message : undefined
  const failedPolicyIndex = isRecord(failure) ? failure.failed_policy_index : undefined
  const hasValidMessage =
    typeof message === 'string' &&
    message.length > 0 &&
    message.length <= maximumFailureMessageLength
  const hasValidPlayer =
    typeof failedPolicyIndex === 'number' &&
    Number.isInteger(failedPolicyIndex) &&
    failedPolicyIndex >= 0 &&
    failedPolicyIndex < playerCount

  if (!hasValidMessage || !hasValidPlayer) {
    return {
      kind: 'failed',
      errorType: 'game_error',
      message: 'Invalid player failure marker',
    }
  }

  return {
    kind: 'failed',
    errorType: 'player_error',
    message,
    failedPolicyIndex,
  }
}

async function readMarker(markerPath: string): Promise<unknown> {
  try {
    const metadata = await stat(markerPath)

    if (!metadata.isFile() || metadata.size > maximumMarkerBytes) {
      throw new GameMarkerError('Game marker must be a regular file of at most 100,000 bytes')
    }

    const markerJson = await readFile(markerPath, 'utf8')

    return JSON.parse(markerJson)
  } catch (error) {
    // Games may create a marker before finishing its JSON write.
    if (isMissingFile(error) || error instanceof SyntaxError) {
      return undefined
    }

    throw error
  }
}

async function replayExists(scratchDirectory: string): Promise<boolean> {
  try {
    const replayPath = join(scratchDirectory, 'replay.replay')
    const metadata = await stat(replayPath)

    return metadata.isFile()
  } catch (error) {
    if (isMissingFile(error)) {
      return false
    }

    throw error
  }
}

function isMissingFile(error: unknown): boolean {
  return error instanceof Error && 'code' in error && error.code === 'ENOENT'
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}
