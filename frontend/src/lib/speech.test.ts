import { describe, expect, it } from 'vitest'
import { Reader, chunkText, pickVoice, type ReaderState, type SpeakHandlers, type Speaker, type Spoken } from './speech'

describe('chunkText', () => {
  it('keeps whole sentences together and every piece knows where it starts', () => {
    const text = 'First one. Second one! Third one? Fourth.'
    const chunks = chunkText(text, 25)
    expect(chunks.map((c) => c.text).join('')).toBe(text)
    for (const c of chunks) expect(text.slice(c.start, c.start + c.text.length)).toBe(c.text)
    expect(chunks.every((c) => c.text.length <= 25)).toBe(true)
    expect(chunks.length).toBeGreaterThan(1)
  })

  it('cuts a sentence that is too long at a space', () => {
    const text = 'word '.repeat(100).trim() + '.'
    const chunks = chunkText(text, 60)
    expect(chunks.map((c) => c.text).join('')).toBe(text)
    for (const c of chunks) {
      expect(text.slice(c.start, c.start + c.text.length)).toBe(c.text)
      expect(c.text.length).toBeLessThanOrEqual(60)
    }
  })

  it('handles text without an end mark and empty text', () => {
    expect(chunkText('No full stop here').map((c) => c.text)).toEqual(['No full stop here'])
    expect(chunkText('')).toEqual([])
    expect(chunkText('   ')).toEqual([])
  })
})

const voice = (name: string, lang: string, localService = true) => ({ name, lang, localService }) as SpeechSynthesisVoice

describe('pickVoice', () => {
  const voices = [voice('Thomas', 'fr-FR'), voice('Google UK English', 'en-GB', false), voice('Samantha', 'en-US'), voice('Ava (Premium)', 'en-US')]
  it('uses the chosen voice when it exists', () => expect(pickVoice(voices, 'Google UK English')?.name).toBe('Google UK English'))
  it('otherwise prefers a premium local US voice, never another language', () => {
    expect(pickVoice(voices, '')?.name).toBe('Ava (Premium)')
    expect(pickVoice(voices, 'Thomas')?.name).toBe('Ava (Premium)')
  })
  it('is null when there is no English voice', () => expect(pickVoice([voice('Thomas', 'fr-FR')], '')).toBeNull())
})

/** A fake voice: each spoken piece waits until the test finishes it. */
function engine() {
  const spoken: { text: string; h: SpeakHandlers }[] = []
  const log: string[] = []
  const speaker: Speaker = {
    speak: (text, h) => { spoken.push({ text, h }); log.push(`speak:${text}`) },
    cancel: () => { log.push('cancel'); spoken.length = 0 },
    pause: () => { log.push('pause') },
    resume: () => { log.push('resume') },
    prepare: (text) => { log.push(`prepare:${text}`) },
    setRate: (r) => { log.push(`rate:${r}`) },
  }
  const events = { states: [] as ReaderState[], spoken: [] as (Spoken | null)[], waiting: [] as boolean[], finished: 0, errors: [] as string[] }
  const reader = new Reader(speaker, {
    onState: (s) => events.states.push(s),
    onSpoken: (s) => events.spoken.push(s),
    onBuffering: (w) => events.waiting.push(w),
    onFinished: () => { events.finished++ },
    onError: (m) => events.errors.push(m),
  })
  const current = () => spoken[spoken.length - 1]
  const finishSpeaking = () => { const s = spoken.shift()!; s.h.onEnd() }
  return { reader, speaker, spoken, current, log, events, finishSpeaking }
}

describe('Reader', () => {
  it('reads the paragraphs one after another and reports the end', () => {
    const t = engine()
    t.reader.setTexts(['One. Two.', 'Three.'])
    t.reader.play(0)
    expect(t.current().text).toBe('One. Two.')
    t.finishSpeaking()
    expect(t.current().text).toBe('Three.')
    t.finishSpeaking()
    expect(t.events.finished).toBe(1)
    expect(t.reader.status).toBe('idle')
  })

  it('reports the word being spoken as a position inside the paragraph', () => {
    const t = engine()
    t.reader.setTexts(['A cat sat. The dog ran away.'])
    t.reader.play(0)
    t.current().h.onBoundary(2)
    expect(t.events.spoken.at(-1)).toMatchObject({ paragraph: 0, char: 2 })
  })

  it('reports the piece being spoken as soon as it starts, before any word', () => {
    const t = engine()
    t.reader.setTexts(['One. Two.'])
    t.reader.play(0)
    expect(t.events.spoken.at(-1)).toEqual({ paragraph: 0, from: 0, to: 9, char: null })
  })

  it('says it is waiting until the voice has started', () => {
    const t = engine()
    t.reader.setTexts(['One.'])
    t.reader.play(0)
    expect(t.events.waiting).toEqual([true])
    t.current().h.onStart()
    expect(t.events.waiting).toEqual([true, false])
  })

  it('gets the next piece ready while this one is spoken, also across paragraphs', () => {
    const t = engine()
    const sentence = 'This is a fairly long sentence that goes on for a while. '
    const long = sentence.repeat(6).trim()  // more than one piece
    const pieces = chunkText(long)
    expect(pieces.length).toBeGreaterThan(1)
    t.reader.setTexts([long, 'Next paragraph.'])
    t.reader.play(0)
    expect(t.log.filter((l) => l.startsWith('prepare'))).toEqual([`prepare:${pieces[1].text}`])
    t.finishSpeaking()  // now the last piece of the paragraph: the one to prepare is in the next paragraph
    expect(t.log.filter((l) => l.startsWith('prepare')).at(-1)).toBe(`prepare:${pieces[2]?.text ?? 'Next paragraph.'}`)
  })

  it('skips pieces that have nothing to say', () => {
    const t = engine()
    t.reader.setTexts(['* * *', 'Real words.'])
    t.reader.play(0)
    expect(t.current().text).toBe('Real words.')
  })

  it('reading from a later paragraph and skipping', () => {
    const t = engine()
    t.reader.setTexts(['A.', 'B.', 'C.'])
    t.reader.play(1)
    expect(t.current().text).toBe('B.')
    t.reader.next()
    expect(t.current().text).toBe('C.')
    t.reader.prev()
    expect(t.current().text).toBe('B.')
    t.reader.prev(); t.reader.prev()
    expect(t.current().text).toBe('A.')
  })

  it('ignores the end of a piece that was replaced or stopped', () => {
    const t = engine()
    t.reader.setTexts(['A.', 'B.'])
    t.reader.play(0)
    const old = t.current()
    t.reader.next()
    old.h.onEnd()  // the cancelled one still reports its end
    expect(t.spoken.map((u) => u.text)).toEqual(['B.'])
    t.reader.stop()
    old.h.onEnd()
    old.h.onBoundary(1)
    expect(t.spoken).toEqual([])
    expect(t.events.finished).toBe(0)
    expect(t.events.spoken.at(-1)).toBeNull()
  })

  it('pauses and resumes only when it makes sense', () => {
    const t = engine()
    t.reader.setTexts(['A.'])
    t.reader.pause(); t.reader.resume()
    expect(t.log).not.toContain('pause')
    t.reader.play(0)
    t.reader.pause()
    expect(t.reader.status).toBe('paused')
    t.reader.resume()
    expect(t.reader.status).toBe('playing')
    expect(t.log.filter((l) => l === 'pause' || l === 'resume')).toEqual(['pause', 'resume'])
  })

  it('passes the speed on, also to a voice chosen later', () => {
    const t = engine()
    t.reader.rate = 0.8
    expect(t.log).toContain('rate:0.8')
    const other = { ...t.speaker, setRate: (r: number) => { t.log.push(`other-rate:${r}`) } }
    t.reader.setSpeaker(other)
    expect(t.log).toContain('other-rate:0.8')
  })

  it('turns errors into a message and stops', () => {
    const t = engine()
    t.reader.setTexts(['A.'])
    t.reader.play(0)
    t.current().h.onError('朗讀失敗（synthesis-failed）')
    expect(t.reader.status).toBe('idle')
    expect(t.events.errors[0]).toContain('synthesis-failed')
  })

  it('ignores an empty chapter', () => {
    const t = engine()
    t.reader.setTexts([])
    t.reader.play(0)
    expect(t.reader.status).toBe('idle')
  })
})
