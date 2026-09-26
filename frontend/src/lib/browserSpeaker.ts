import type { SpeakHandlers, Speaker } from './speech'

/** Speaks with the voices built into the browser. */
export class BrowserSpeaker implements Speaker {
  private synth: SpeechSynthesis
  private makeUtterance: (text: string) => SpeechSynthesisUtterance
  private getVoice: () => SpeechSynthesisVoice | null
  private rate = 1

  constructor(synth: SpeechSynthesis, makeUtterance: (text: string) => SpeechSynthesisUtterance, getVoice: () => SpeechSynthesisVoice | null) {
    this.synth = synth
    this.makeUtterance = makeUtterance
    this.getVoice = getVoice
  }

  setRate(rate: number) { this.rate = rate }

  speak(text: string, h: SpeakHandlers) {
    const voice = this.getVoice()
    const utterance = this.makeUtterance(text)
    utterance.lang = voice?.lang ?? 'en-US'
    if (voice) utterance.voice = voice
    utterance.rate = this.rate
    utterance.onstart = () => h.onStart()
    utterance.onboundary = (e) => { if (!e.name || e.name === 'word') h.onBoundary(e.charIndex) }
    utterance.onend = () => h.onEnd()
    utterance.onerror = (e) => h.onError(e.error === 'not-allowed' ? '瀏覽器不允許朗讀，請先點一下頁面再試' : `朗讀失敗（${e.error}）`)
    this.synth.speak(utterance)
  }

  cancel() { this.synth.cancel() }
  pause() { this.synth.pause() }
  resume() { this.synth.resume() }
}
