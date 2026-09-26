import type { SpeakHandlers, Speaker } from './speech'

/** Where each word starts in a text, as a fraction (0–1) of the time it takes to say it. A voice does not report
 * word times, so they are estimated: longer words take longer, and commas and full stops are followed by pauses. */
export function wordStarts(text: string): { char: number; at: number }[] {
  const words = [...text.matchAll(/\S+/g)].map((m) => {
    const word = m[0]
    const letters = word.replace(/[^\p{L}\p{N}]/gu, '').length
    const pause = /[.!?…]["'”’)\]]*$/.test(word) ? 5 : /[,;:—–-]["'”’)\]]*$/.test(word) ? 2.5 : 0
    return { char: m.index ?? 0, weight: Math.max(1, letters) + 1 + pause }
  })
  const total = words.reduce((sum, w) => sum + w.weight, 0) || 1
  let seen = 0
  return words.map((w) => {
    const at = seen / total
    seen += w.weight
    return { char: w.char, at }
  })
}

/** The character of the word being said `fraction` of the way through the text. */
export function charAtFraction(starts: { char: number; at: number }[], fraction: number): number {
  let found = starts[0]?.char ?? 0
  for (const s of starts) {
    if (s.at <= fraction) found = s.char
    else break
  }
  return found
}

export interface AudioLike {
  playbackRate: number
  preservesPitch: boolean
  currentTime: number
  duration: number
  onended: ((e: Event) => void) | null
  onerror: OnErrorEventHandler
  play(): Promise<void>
  pause(): void
}

export interface NeuralDeps {
  /** The mp3 of a text in a voice, as a playable address. */
  fetchAudio: (text: string, voice: string) => Promise<string>
  release: (url: string) => void
  createAudio: (url: string) => AudioLike
  voice: () => string
  every: (fn: () => void, ms: number) => () => void  // repeat; returns the stop function
}

const KEEP = 12  // recently made pieces kept in memory

/** Speaks with the natural voice made by the backend: fetches the audio of each piece (the next piece is fetched
 * while this one plays) and plays it, following along to tell which word is being said. */
export class NeuralSpeaker implements Speaker {
  private deps: NeuralDeps
  private rate = 1
  private token = 0
  private paused = false
  private audio: AudioLike | null = null
  private begin: (() => void) | null = null  // starts the sound once it is ready and not paused
  private stopTicking: (() => void) | null = null
  private cache = new Map<string, Promise<string>>()

  constructor(deps: NeuralDeps) {
    this.deps = deps
  }

  setRate(rate: number) {
    this.rate = rate
    if (this.audio) this.audio.playbackRate = rate
  }

  private load(text: string): Promise<string> {
    const key = `${this.deps.voice()}|${text}`
    let found = this.cache.get(key)
    if (!found) {
      found = this.deps.fetchAudio(text, this.deps.voice())
      found.catch(() => this.cache.delete(key))  // a failed fetch is tried again next time
      this.cache.set(key, found)
      while (this.cache.size > KEEP) {
        const oldest = this.cache.keys().next().value as string
        const gone = this.cache.get(oldest)
        this.cache.delete(oldest)
        gone?.then((url) => this.deps.release(url), () => {})
      }
    }
    return found
  }

  prepare(text: string) {
    this.load(text).catch(() => {})
  }

  speak(text: string, h: SpeakHandlers) {
    this.halt()
    const token = ++this.token
    this.load(text).then((url) => {
      if (token !== this.token) return
      const audio = this.deps.createAudio(url)
      audio.playbackRate = this.rate
      audio.preservesPitch = true
      this.audio = audio
      const starts = wordStarts(text)
      let lastChar = -1
      audio.onended = () => {
        if (token !== this.token) return
        this.halt()
        h.onEnd()
      }
      audio.onerror = () => { if (token === this.token) h.onError('播放語音失敗') }
      this.begin = () => {
        this.begin = null
        audio.play().then(() => {
          if (token !== this.token) return
          h.onStart()
          h.onBoundary(starts[0]?.char ?? 0)
          lastChar = starts[0]?.char ?? 0
          this.stopTicking = this.deps.every(() => {
            if (!audio.duration || audio.duration === Infinity) return
            const char = charAtFraction(starts, audio.currentTime / audio.duration)
            if (char !== lastChar) { lastChar = char; h.onBoundary(char) }
          }, 60)
        }, () => { if (token === this.token) h.onError('瀏覽器不允許播放，請先點一下頁面再試') })
      }
      if (!this.paused) this.begin()
    }, (e: Error) => {
      if (token === this.token) h.onError(e.message || '語音產生失敗')
    })
  }

  /** Stop the sound and the following-along (the pieces already fetched are kept). */
  private halt() {
    this.stopTicking?.()
    this.stopTicking = null
    this.audio?.pause()
    this.audio = null
    this.begin = null
  }

  cancel() {
    this.token++
    this.paused = false
    this.halt()
  }

  pause() {
    this.paused = true
    this.audio?.pause()
  }

  resume() {
    this.paused = false
    if (this.begin) this.begin()
    else void this.audio?.play()
  }
}
