import { readFile } from 'node:fs/promises'
import { prepareGameFiles, writeEpisodeOutput } from './episode-files.mts'
import { waitForGameOutcome } from './game-outcome.mts'
import { GameProcess } from './game-process.mts'
import type { GameOutcome, ProcessInput } from './protocol.mts'

const inputPath = process.env.WORLD_INPUT_PATH
const outputPath = process.env.WORLD_OUTPUT_PATH
const scratchDirectory = process.env.WORLD_SCRATCH_PATH

if (!inputPath || !outputPath || !scratchDirectory) {
  throw new Error('Conductor must supply input, output and scratch paths')
}

const inputJson = await readFile(inputPath, 'utf8')
const processInput: ProcessInput = JSON.parse(inputJson)

if (processInput.protocol !== 1) {
  throw new Error('Unsupported Conductor protocol')
}

const [executable, ...arguments_] = process.argv.slice(2)

if (!executable) {
  throw new Error('An operator-installed game executable is required')
}

const gameEnvironment = await prepareGameFiles({
  processInput,
  scratchDirectory,
})

const gameProcess = new GameProcess({
  executable,
  arguments_,
  environment: gameEnvironment,
  scratchDirectory,
})

let outcome: GameOutcome

try {
  outcome = await waitForGameOutcome({
    gameProcess,
    scratchDirectory,
    deadlineAt: processInput.deadlineAt,
    playerCount: processInput.policies.length,
  })
} finally {
  await gameProcess.stop()
}

await writeEpisodeOutput({
  outputPath,
  scratchDirectory,
  outcome,
  diagnostics: gameProcess.diagnostics,
})
