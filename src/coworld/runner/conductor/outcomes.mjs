import { readMarker, replayExists } from './files.mjs'

export async function readOutcome(directory, seats) {
  const result = await readMarker(directory, 'results.json')
  // Complete artifacts take precedence over a failure marker, as in the existing Coworld runner.
  if (result && (await replayExists(directory))) {
    if (!Array.isArray(result.scores) || result.scores.length !== seats || !result.scores.every(Number.isFinite)) {
      return { kind: 'failed', errorType: 'results_malformed', message: 'Invalid per-seat scores' }
    }
    return { kind: 'completed', result }
  }
  const failure = await readMarker(directory, 'failure.json')
  if (!failure) return undefined
  if (
    typeof failure.message !== 'string' ||
    !failure.message.length ||
    failure.message.length > 2000 ||
    !Number.isInteger(failure.failed_policy_index) ||
    failure.failed_policy_index < 0 ||
    failure.failed_policy_index >= seats
  ) {
    return { kind: 'failed', errorType: 'game_error', message: 'Invalid player failure marker' }
  }
  return {
    kind: 'failed',
    errorType: 'player_error',
    message: failure.message,
    failedPolicyIndex: failure.failed_policy_index,
  }
}
