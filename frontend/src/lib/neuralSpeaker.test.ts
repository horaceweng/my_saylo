import { describe, expect, it } from 'vitest'
import { NeuralSpeaker, charAtFraction, wordStarts, type AudioLike } from './neuralSpeaker'
import type { SpeakHandlers } from './speech'

describe('wordStarts', () => {
  it('starts at the first word and moves forward through every word', () => {
    const text = 'The quick brown fox, jumped.'
    const starts = wordStarts(text)
    expect(starts.map((s) => text.slice(s.char).split(' ')[0])).toEqual(['The', 'quick', 'brown', 'fox,', 'jumped.'])
    expect(starts[0].at).toBe(0)
    for (let i = 1; i < starts.length; i++) expect(starts[i].at).toBeGreaterThan(starts[i - 1].at)
    expect(starts.at(-1)!.at).toBeLessThan(1)
  })

  it('gives longer words more time and leaves room for the pause after a comma', () => {
    const [a, b, c] = wordStarts('a extraordinarily, big')
    expect(b.at - a.at).toBeLessThan(c.at - b.at)  // the long word plus its comma take longer than the short one
  })

  it('is empty for empty text', () => expect(wordStarts('  ')).toEqual([]))
})

describe('charAtFraction', () => {
  const starts = wordStarts('one two three four')
  it('finds the word being said', () => {
    expect(charAtFraction(starts, 0)).toBe(0)
    expect(charAtFraction(starts, 0.999)).toBe(starts.at(-1)!.char)
    expect(charAtFraction(starts, starts[2].at + 0.001)).toBe(starts[2].char)
  })
})

/** A fake audio element and clock: the test decides when the sound plays, ticks and ends. */
function setup(options: { voice?: string; fail?: boolean } = {}) {
  const fetched: string[] = []
  const released: string[] = []
  const players: (AudioLike & { played: number; paused: number })[] = []
  let tick: () => void = () => {}
  const events: string[] = []
  const speaker = new NeuralSpeaker({
    fetchAudio: async (text, voice) => {
      fetched.push(`${voice}:${text}`)
      if (options.fail) throw new Error('boom')
      return `blob:${text}`
    },
    release: (url) => released.push(url),
    createAudio: () => {
      const audio = { playbackRate: 1, preservesPitch: false, currentTime: 0, duration: 10, onended: null, onerror: null, played: 0, paused: 0,
        play: async () => { audio.played++ }, pause: () => { audio.paused++ } } as AudioLike & { played: number; paused: number }
      players.push(audio)
      return audio
    },
    voice: () => options.voice ?? 'af_heart',
    every: (fn) => { tick = fn; return () => { tick = () => {} } },
  })
  const handlers: SpeakHandlers = {
    onStart: () => events.push('start'),
    onBoundary: (c) => events.push(`at:${c}`),
    onEnd: () => events.push('end'),
    onError: (m) => events.push(`error:${m}`),
  }
  const settle = () => new Promise((r) => setTimeout(r, 0))
  return { speaker, fetched, released, players, events, handlers, settle, tick: () => tick() }
}

describe('NeuralSpeaker', () => {
  it('plays the fetched audio and reports the words as the time passes', async () => {
    const t = setup()
    t.speaker.setRate(1.15)
    t.speaker.speak('one two three four', t.handlers)
    await t.settle()
    expect(t.fetched).toEqual(['af_heart:one two three four'])
    expect(t.players[0]).toMatchObject({ played: 1, playbackRate: 1.15, preservesPitch: true })
    expect(t.events.slice(0, 2)).toEqual(['start', 'at:0'])
    t.players[0].currentTime = 9.9
    t.tick()
    expect(t.events.at(-1)).toBe('at:14')  // "four"
    t.tick()
    expect(t.events.filter((e) => e === 'at:14')).toHaveLength(1)  // a word is reported once
    t.players[0].onended?.(new Event('ended'))
    expect(t.events.at(-1)).toBe('end')
  })

  it('fetches a piece only once, whether it was prepared or spoken twice', async () => {
    const t = setup()
    t.speaker.prepare('Next one.')
    t.speaker.speak('Next one.', t.handlers)
    await t.settle()
    t.speaker.speak('Next one.', t.handlers)
    await t.settle()
    expect(t.fetched).toEqual(['af_heart:Next one.'])
  })

  it('does not play a piece that was replaced while it was still being made', async () => {
    const t = setup()
    t.speaker.speak('old', t.handlers)
    t.speaker.speak('new', t.handlers)
    await t.settle()
    expect(t.players).toHaveLength(1)
    t.speaker.cancel()
    await t.settle()
    expect(t.players[0].paused).toBeGreaterThan(0)
  })

  it('waits for resume when paused before the sound was ready', async () => {
    const t = setup()
    t.speaker.pause()
    t.speaker.speak('wait for it', t.handlers)
    await t.settle()
    expect(t.players[0].played).toBe(0)
    t.speaker.resume()
    await t.settle()
    expect(t.players[0].played).toBe(1)
  })

  it('pauses and resumes what is playing', async () => {
    const t = setup()
    t.speaker.speak('some words here', t.handlers)
    await t.settle()
    t.speaker.pause()
    expect(t.players[0].paused).toBe(1)
    t.speaker.resume()
    expect(t.players[0].played).toBe(2)
  })

  it('reports why the voice failed, and tries again next time', async () => {
    const t = setup({ fail: true })
    t.speaker.speak('anything', t.handlers)
    await t.settle()
    expect(t.events).toEqual(['error:boom'])
    t.speaker.speak('anything', t.handlers)
    await t.settle()
    expect(t.fetched).toHaveLength(2)
  })

  it('releases the oldest pieces so memory does not grow', async () => {
    const t = setup()
    for (let i = 0; i < 15; i++) t.speaker.prepare(`piece ${i}`)
    await t.settle()
    expect(t.released).toEqual(['blob:piece 0', 'blob:piece 1', 'blob:piece 2'])
  })
})
