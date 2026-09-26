/** Reading text aloud with the browser's own speech voices (free, works offline with the voices macOS ships). */

export interface Chunk {
  text: string
  start: number  // where it begins in the paragraph
}

/** A paragraph as pieces of whole sentences, each at most `max` characters: very long utterances get cut off by some voices. */
export function chunkText(text: string, max = 240): Chunk[] {
  const sentences: Chunk[] = []
  const re = /[^.!?…]*[.!?…]+["'”’)\]]*\s*|[^.!?…]+$/g
  let m: RegExpExecArray | null
  while ((m = re.exec(text)) !== null) {
    if (m[0] === '') { re.lastIndex += 1; continue }
    sentences.push({ text: m[0], start: m.index })
  }
  const chunks: Chunk[] = []
  for (const s of sentences) {
    const last = chunks[chunks.length - 1]
    if (last && last.text.length + s.text.length <= max) last.text += s.text
    else chunks.push({ ...s })
  }
  // one sentence longer than the limit: cut it at a space
  return chunks.flatMap((c) => {
    if (c.text.length <= max) return [c]
    const parts: Chunk[] = []
    let from = 0
    while (from < c.text.length) {
      let to = Math.min(c.text.length, from + max)
      if (to < c.text.length) {
        const space = c.text.lastIndexOf(' ', to)
        if (space > from) to = space + 1
      }
      parts.push({ text: c.text.slice(from, to), start: c.start + from })
      from = to
    }
    return parts
  }).filter((c) => c.text.trim() !== '')
}

/** The voice to use: the one the learner chose, else the best-sounding English one. */
export function pickVoice(voices: SpeechSynthesisVoice[], chosen: string): SpeechSynthesisVoice | null {
  const english = voices.filter((v) => /^en[-_]/i.test(v.lang) || v.lang.toLowerCase() === 'en')
  const saved = english.find((v) => v.name === chosen)
  if (saved) return saved
  const rank = (v: SpeechSynthesisVoice) =>
    (/premium|enhanced/i.test(v.name) ? 0 : 4) + (/^en[-_]US/i.test(v.lang) ? 0 : 2) + (v.localService ? 0 : 1)
  return [...english].sort((a, b) => rank(a) - rank(b))[0] ?? null
}

export type ReaderState = 'idle' | 'playing' | 'paused'

/** Where the voice is: the paragraph, the piece being spoken, and the word (null until it is known). */
export interface Spoken {
  paragraph: number
  from: number
  to: number
  char: number | null
}

export interface SpeakHandlers {
  /** The sound has really started (a natural voice needs a moment to make it). */
  onStart: () => void
  /** The voice is at this character of the text it was given. */
  onBoundary: (charIndex: number) => void
  onEnd: () => void
  onError: (message: string) => void
}

/** Something that can say a short text: the browser's voices, or the natural voice made by the backend. */
export interface Speaker {
  speak(text: string, handlers: SpeakHandlers): void
  cancel(): void
  pause(): void
  resume(): void
  /** This text will be spoken soon: get it ready. */
  prepare?(text: string): void
  setRate(rate: number): void
}

export interface ReaderEvents {
  onState: (state: ReaderState) => void
  onSpoken: (spoken: Spoken | null) => void
  /** Waiting for the voice to start (true), or it has started or stopped (false). */
  onBuffering: (waiting: boolean) => void
  /** The last paragraph has been read. */
  onFinished: () => void
  onError: (message: string) => void
}

/** Reads paragraphs one after another, piece by piece, and reports where it is. */
export class Reader {
  private texts: string[] = []
  private chunks: Chunk[] = []
  private p = 0
  private c = 0
  private generation = 0  // a stopped or skipped piece may still report its end: those reports are ignored
  private state: ReaderState = 'idle'
  private waiting = false
  private speaker: Speaker
  private events: ReaderEvents
  private speed = 1

  constructor(speaker: Speaker, events: ReaderEvents) {
    this.speaker = speaker
    this.events = events
  }

  /** Change the voice source (stops what is being read). */
  setSpeaker(speaker: Speaker) {
    if (speaker === this.speaker) return
    this.stop()
    this.speaker = speaker
    this.speaker.setRate(this.speed)
  }

  set rate(value: number) {
    this.speed = value
    this.speaker.setRate(value)
  }

  setTexts(texts: string[]) { this.texts = texts }
  get current() { return this.p }
  get status() { return this.state }

  play(paragraph: number) {
    if (paragraph < 0 || paragraph >= this.texts.length) return
    this.begin(paragraph)
  }

  next() { if (this.state !== 'idle') this.p + 1 < this.texts.length ? this.begin(this.p + 1) : this.finish() }
  prev() { if (this.state !== 'idle') this.begin(Math.max(0, this.p - 1)) }

  pause() {
    if (this.state !== 'playing') return
    this.speaker.pause()
    this.setState('paused')
  }

  resume() {
    if (this.state !== 'paused') return
    this.speaker.resume()
    this.setState('playing')
  }

  stop() {
    this.generation++
    this.speaker.cancel()
    this.setState('idle')
    this.setWaiting(false)
    this.events.onSpoken(null)
  }

  private setState(state: ReaderState) {
    if (state === this.state) return
    this.state = state
    this.events.onState(state)
  }

  private setWaiting(waiting: boolean) {
    if (waiting === this.waiting) return
    this.waiting = waiting
    this.events.onBuffering(waiting)
  }

  private begin(paragraph: number) {
    this.generation++
    this.speaker.cancel()
    this.p = paragraph
    this.chunks = chunkText(this.texts[paragraph])
    this.c = 0
    this.setState('playing')
    this.speak()
  }

  private finish() {
    this.stop()
    this.events.onFinished()
  }

  /** The text of the piece after the one at (p, c), which may be in the next paragraph. */
  private upcoming(): string | null {
    const here = this.chunks[this.c + 1]
    if (here) return here.text
    const next = this.texts[this.p + 1]
    return next ? chunkText(next)[0]?.text ?? null : null
  }

  private speak(): void {
    // the end of this paragraph: on to the next
    if (this.c >= this.chunks.length) {
      if (this.p + 1 < this.texts.length) return this.begin(this.p + 1)
      return this.finish()
    }
    const chunk = this.chunks[this.c]
    // headings, rules and the like ("* * *") have nothing to say
    if (!/[\p{L}\p{N}]/u.test(chunk.text)) {
      this.c++
      return this.speak()
    }
    const generation = this.generation
    const spoken = (char: number | null): Spoken => ({ paragraph: this.p, from: chunk.start, to: chunk.start + chunk.text.length, char })
    const current = () => generation === this.generation
    this.events.onSpoken(spoken(null))
    this.setWaiting(true)
    this.speaker.speak(chunk.text, {
      onStart: () => { if (current()) this.setWaiting(false) },
      onBoundary: (charIndex) => { if (current()) this.events.onSpoken(spoken(chunk.start + charIndex)) },
      onEnd: () => {
        if (!current()) return
        this.c++
        this.speak()
      },
      onError: (message) => {
        if (!current()) return
        this.stop()
        this.events.onError(message)
      },
    })
    const following = this.upcoming()
    if (following) this.speaker.prepare?.(following)
  }
}
