import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { runInNewContext } from 'node:vm'
import { gzipSync } from 'node:zlib'

test('loads a compressed replay, announces readiness, and autoplays in a loop', async () => {
  const html = readFileSync(
    new URL('../src/coworld/examples/paintarena/game/client/replay.html', import.meta.url),
    'utf8'
  )
  const script = html.match(/<script\b[^>]*>([\s\S]*?)<\/script>/)[1]
  const frame = {
    width: 2,
    height: 1,
    tick: 0,
    max_ticks: 2,
    positions: [[0, 0]],
    tile_owners: [0, -1],
    scores: [1],
  }
  const replay = { player_names: ['Test player'], frames: [frame, { ...frame, tick: 1 }], results: {} }
  const elements = new Map()
  const document = {
    createElement: () => ({
      style: { setProperty() {} },
      classList: { add() {} },
      dataset: {},
      replaceChildren(...children) {
        this.children = children
      },
      getBoundingClientRect: () => ({ width: 100, height: 100 }),
    }),
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, this.createElement())
      return elements.get(id)
    },
  }
  const notifications = []
  const location = { hash: '#replay=https%3A%2F%2Fexample.test%2Freplay.gz', search: '' }
  let advance
  await runInNewContext(script, {
    document,
    location,
    window: {
      parent: { postMessage: (message) => notifications.push(message) },
      getComputedStyle: () => ({ columnGap: '0' }),
      addEventListener() {},
    },
    URLSearchParams,
    Response,
    Blob,
    TextDecoder,
    DecompressionStream,
    fetch: async (url) => {
      assert.equal(url, 'https://example.test/replay.gz')
      return new Response(gzipSync(JSON.stringify(replay)))
    },
    setInterval(callback) {
      advance = callback
      return 1
    },
    clearInterval() {
      advance = undefined
    },
    setTimeout: (callback) => callback(),
  })

  assert.ok(notifications.some((message) => message.src === 'coworld-replay' && message.type === 'ready'))
  assert.equal(elements.get('scores').children[0].textContent, 'Test player: 1')
  assert.equal(elements.get('scrubber').value, 0)
  advance()
  assert.equal(elements.get('scrubber').value, 1)
  advance()
  assert.equal(elements.get('scrubber').value, 0)
})
