import { describe, expect, it } from 'vitest'
import { readNdjson } from './ndjson'

const streamOf = (...chunks: string[]) =>
  new ReadableStream<Uint8Array>({
    start(controller) {
      const enc = new TextEncoder()
      chunks.forEach((c) => controller.enqueue(enc.encode(c)))
      controller.close()
    },
  })

const collect = async (s: ReadableStream<Uint8Array>) => {
  const out: unknown[] = []
  for await (const item of readNdjson(s)) out.push(item)
  return out
}

describe('readNdjson', () => {
  it('yields one item per line', async () => {
    expect(await collect(streamOf('{"a":1}\n{"a":2}\n'))).toEqual([{ a: 1 }, { a: 2 }])
  })
  it('handles a line split across chunks, including inside a multi-byte character', async () => {
    const line = JSON.stringify({ t: '讓我們退一步' }) + '\n'
    const bytes = new TextEncoder().encode(line)
    const cut = bytes.indexOf(0xe8) + 1 // middle of the first 3-byte character
    const s = new ReadableStream<Uint8Array>({
      start(c) { c.enqueue(bytes.slice(0, cut)); c.enqueue(bytes.slice(cut)); c.close() },
    })
    expect(await collect(s)).toEqual([{ t: '讓我們退一步' }])
  })
  it('accepts a last line without a trailing newline and skips blank lines', async () => {
    expect(await collect(streamOf('{"a":1}\n\n', '{"a":2}'))).toEqual([{ a: 1 }, { a: 2 }])
  })
})
