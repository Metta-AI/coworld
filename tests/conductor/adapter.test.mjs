import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'
import { readOutcome } from '../../src/coworld/runner/conductor/game-outcome.mts'

// The installed game needs the real binary because the adapter deliberately scrubs Bazel launcher variables.
const node = resolve(process.env.JS_BINARY__NODE_BINARY ?? process.execPath)
const adapter = fileURLToPath(
  new URL('../../src/coworld/runner/conductor/game-hosted.mts', import.meta.url)
)

test('a game receives the resolved roster and returns a complete replay', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'conductor-adapter-'))
  try {
    const policy = join(directory, 'policy.bas')
    const input = join(directory, 'input.json')
    const output = join(directory, 'output.json')
    const game = join(directory, 'game.mjs')
    await writeFile(policy, '10 END\n')
    await writeFile(
      input,
      JSON.stringify({
        protocol: 1,
        policies: [{ role: 'seat-0', path: policy }],
        seed: 42,
        config: { players: [{ name: 'Alice', team: 3 }], testMarker: 'preserved' },
        deadlineAt: Date.now() + 20_000,
      })
    )
    await writeFile(
      game,
      `
      import { readFile, writeFile } from 'node:fs/promises';
      import assert from 'node:assert/strict';
      const config = JSON.parse(await readFile(new URL(process.env.COGAME_CONFIG_URI)));
      const { schema, seats } = JSON.parse(await readFile(new URL(process.env.COGAME_PLAYER_SEATS_URI)));
      assert.equal(schema, 'coworld-player-seats/2');
      await writeFile(new URL(seats[0].annotations_uri), '');
      assert.deepEqual(config.players, [{ name: 'Alice', team: 3 }]);
      assert.equal(config.testMarker, 'preserved');
      assert.equal(seats[0].artifact_uri.startsWith('file:'), true);
      assert.equal(await readFile(new URL(seats[0].file_uri), 'utf8'), '10 END\\n');
      await writeFile(new URL(process.env.COGAME_SAVE_REPLAY_URI), 'replay');
      await writeFile(new URL(process.env.COGAME_RESULTS_URI), JSON.stringify({ scores: [7] }));
      setInterval(() => {}, 1000);
    `
    )
    const child = spawn(node, [adapter, node, game], {
      env: {
        ...process.env,
        WORLD_INPUT_PATH: input,
        WORLD_OUTPUT_PATH: output,
        WORLD_SCRATCH_PATH: directory,
      },
      stdio: 'inherit',
    })
    const exit = await new Promise((resolve, reject) => {
      child.on('error', reject)
      child.on('close', resolve)
    })
    assert.equal(exit, 0)
    const result = JSON.parse(await readFile(output))
    assert.deepEqual(
      result.result,
      { kind: 'completed', result: { scores: [7] } },
      await readFile(join(directory, 'diagnostics.log'), 'utf8')
    )
    assert.equal(await readFile(join(directory, 'replay.replay'), 'utf8'), 'replay')
  } finally {
    await rm(directory, { recursive: true, force: true })
  }
})

test('complete artifacts win over a failure marker, and failure seats must exist', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'conductor-outcome-'))
  try {
    await writeFile(
      join(directory, 'failure.json'),
      JSON.stringify({ message: 'Policy stopped', failed_policy_index: 1 })
    )
    assert.deepEqual(await readOutcome({ scratchDirectory: directory, playerCount: 2 }), {
      kind: 'failed',
      errorType: 'player_error',
      message: 'Policy stopped',
      failedPolicyIndex: 1,
    })
    assert.equal(
      (await readOutcome({ scratchDirectory: directory, playerCount: 1 })).errorType,
      'game_error'
    )
    await writeFile(join(directory, 'results.json'), JSON.stringify({ scores: [7, 3] }))
    await writeFile(join(directory, 'replay.replay'), 'replay')
    assert.deepEqual(await readOutcome({ scratchDirectory: directory, playerCount: 2 }), {
      kind: 'completed',
      result: { scores: [7, 3] },
    })
  } finally {
    await rm(directory, { recursive: true, force: true })
  }
})
