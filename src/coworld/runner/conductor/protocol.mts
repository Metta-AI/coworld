// Conductor validates the process envelope before launching this adapter. These types describe
// the fields consumed here; the runner's published process-input.schema.json owns the wire format.
export type ProcessInput = {
  protocol: 1
  deadlineAt: number
  seed: number
  config: Record<string, unknown>
  policies: {
    role: string
    path: string
  }[]
}

export type GameOutcome =
  | {
      kind: 'completed'
      result: Record<string, unknown>
    }
  | {
      kind: 'failed'
      errorType: 'episode_timeout' | 'game_error' | 'results_malformed' | 'player_error'
      message: string
      failedPolicyIndex?: number
    }

export type OutputArtifact = {
  name: string
  path: string
  mediaType: string
}
