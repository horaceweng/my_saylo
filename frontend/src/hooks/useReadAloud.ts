import { useCallback, useEffect, useRef, useState } from 'react'
import { api, fetchSpeech } from '../api/client'
import type { TtsStatus } from '../api/types'
import { BrowserSpeaker } from '../lib/browserSpeaker'
import { NeuralSpeaker } from '../lib/neuralSpeaker'
import { loadNaturalVoice, loadSpeechEngine, loadSpeechRate, loadVoiceName, saveSpeechRate } from '../lib/prefs'
import { Reader, pickVoice, type ReaderState, type Speaker, type Spoken } from '../lib/speech'

export const speechSupported = (): boolean => typeof window !== 'undefined' && 'speechSynthesis' in window && 'SpeechSynthesisUtterance' in window

/** The English voices this browser has (the list arrives a moment after the page opens). */
export function useVoices(): SpeechSynthesisVoice[] {
  const [voices, setVoices] = useState<SpeechSynthesisVoice[]>([])
  useEffect(() => {
    if (!speechSupported()) return
    const read = () => setVoices(window.speechSynthesis.getVoices().filter((v) => /^en([-_]|$)/i.test(v.lang)))
    read()
    window.speechSynthesis.addEventListener('voiceschanged', read)
    return () => window.speechSynthesis.removeEventListener('voiceschanged', read)
  }, [])
  return voices
}

/** Can the natural voice be used? (null until the backend has answered) */
export function useTtsStatus(): TtsStatus | null {
  const [status, setStatus] = useState<TtsStatus | null>(null)
  useEffect(() => {
    let stale = false
    api.ttsStatus().then((s) => !stale && setStatus(s)).catch(() => undefined)
    return () => { stale = true }
  }, [])
  return status
}

/** Read `texts` (the paragraphs on screen) aloud. Changing the texts, or leaving the page, stops the reading. */
export function useReadAloud(texts: string[], onFinished: () => void) {
  const [state, setState] = useState<ReaderState>('idle')
  const [spoken, setSpoken] = useState<Spoken | null>(null)
  const [buffering, setBuffering] = useState(false)
  const [error, setError] = useState('')
  const [rate, setRateState] = useState(loadSpeechRate)
  const voices = useVoices()
  const status = useTtsStatus()
  const finished = useRef(onFinished)
  finished.current = onFinished
  const voicesRef = useRef(voices)
  voicesRef.current = voices
  const statusRef = useRef(status)
  statusRef.current = status

  const speakers = useRef<{ natural: Speaker; browser: Speaker | null }>(null)
  if (!speakers.current) {
    speakers.current = {
      natural: new NeuralSpeaker({
        fetchAudio: fetchSpeech,
        release: (url) => URL.revokeObjectURL(url),
        createAudio: (url) => new Audio(url),
        voice: () => loadNaturalVoice() || statusRef.current?.default_voice || 'af_heart',
        every: (fn, ms) => { const id = window.setInterval(fn, ms); return () => window.clearInterval(id) },
      }),
      browser: speechSupported()
        ? new BrowserSpeaker(window.speechSynthesis, (t) => new SpeechSynthesisUtterance(t), () => pickVoice(voicesRef.current, loadVoiceName()))
        : null,
    }
  }
  const natural = () => loadSpeechEngine() === 'auto' && statusRef.current?.available === true
  const supported = natural() || speakers.current.browser !== null

  const reader = useRef<Reader | null>(null)
  if (!reader.current) {
    reader.current = new Reader(speakers.current.browser ?? speakers.current.natural, {
      onState: setState,
      onSpoken: setSpoken,
      onBuffering: setBuffering,
      onFinished: () => finished.current(),
      onError: setError,
    })
    reader.current.rate = loadSpeechRate()
  }

  useEffect(() => {
    reader.current?.stop()
    reader.current?.setTexts(texts)
  }, [texts])

  useEffect(() => () => reader.current?.stop(), [])

  const setRate = useCallback((r: number) => {
    saveSpeechRate(r)
    setRateState(r)
    if (reader.current) reader.current.rate = r
  }, [])

  return {
    supported,
    engine: (natural() ? 'natural' : 'browser') as 'natural' | 'browser',
    state, spoken, buffering, error, rate, setRate,
    play: (paragraph: number) => {
      setError('')
      const pick = natural() ? speakers.current!.natural : speakers.current!.browser
      if (!pick || !reader.current) return
      reader.current.setSpeaker(pick)  // the choice in Settings applies from the next start
      reader.current.play(paragraph)
    },
    pause: () => reader.current?.pause(),
    resume: () => reader.current?.resume(),
    stop: () => reader.current?.stop(),
    next: () => reader.current?.next(),
    prev: () => reader.current?.prev(),
  }
}
