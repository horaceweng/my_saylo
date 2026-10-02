import { afterEach, describe, expect, it, vi } from 'vitest'
import { streamExplain } from './client'

const ndjson = (...events: object[]) =>
  new Response(new ReadableStream<Uint8Array>({
    start(c) { c.enqueue(new TextEncoder().encode(events.map((e) => JSON.stringify(e) + '\n').join(''))); c.close() },
  }), { status: 200 })

afterEach(() => vi.unstubAllGlobals())

describe('streamExplain', () => {
  it('reports its place in the line, then carries on to the answer', async () => {
    const final = { translation: '譯', structure: 'S', grammar_points: [], phrases: [], similar_examples: [] }
    vi.stubGlobal('fetch', vi.fn(async () => ndjson({ type: 'queued', position: 2 }, { type: 'queued', position: 1 }, { type: 'partial', data: { translation: '譯' } }, { type: 'done', data: final })))
    const queued: number[] = [], partials: unknown[] = []
    const result = await streamExplain('Hi.', '', (p) => partials.push(p), new AbortController().signal, (n) => queued.push(n))
    expect(queued).toEqual([2, 1])
    expect(partials).toHaveLength(1)
    expect(result).toEqual(final)
  })

  it('works for a caller that does not care about the line (queued events are skipped)', async () => {
    const final = { translation: '譯' }
    vi.stubGlobal('fetch', vi.fn(async () => ndjson({ type: 'queued', position: 1 }, { type: 'done', data: final })))
    expect(await streamExplain('Hi.', '', () => undefined, new AbortController().signal)).toEqual(final)
  })

  it('a refused request (a daily limit) shows the reason the server gave', async () => {
    const detail = '今天的 AI 使用次數已達上限（300／300 次）。將在 10/03 00:00（台北時間）重置，之後就可以再用。'
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ detail }), { status: 429 })))
    await expect(streamExplain('Hi.', '', () => undefined, new AbortController().signal)).rejects.toThrow(detail)
  })

  it('without a reason it says what the status was', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('oops', { status: 502 })))
    await expect(streamExplain('Hi.', '', () => undefined, new AbortController().signal)).rejects.toThrow('502')
  })
})
