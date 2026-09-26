/** Preferences kept in this browser. (Difficulty colours and "my level" live in wordMarks.ts and are edited
 * on the same settings page.) */

export const SKIP_OPTIONS = [3, 5, 10, 15, 30]
export const DEFAULT_SKIP_SECONDS = 5

function read(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

function write(key: string, value: string) {
  try {
    localStorage.setItem(key, value)
  } catch {
    /* the choice just is not remembered */
  }
}

/** How far the back / forward buttons jump. */
export function loadSkipSeconds(): number {
  const n = Number(read('skip-seconds'))
  return SKIP_OPTIONS.includes(n) ? n : DEFAULT_SKIP_SECONDS
}
export const saveSkipSeconds = (seconds: number) => write('skip-seconds', String(seconds))

/** Are translations shown under each sentence when a video or podcast is opened? */
export const loadShowTranslation = (): boolean => read('show-translation') !== 'off'
export const saveShowTranslation = (on: boolean) => write('show-translation', on ? 'on' : 'off')

/** Reading aloud: the voice's name (empty = the best English one) and its speed. */
export const SPEECH_RATES = [0.7, 0.85, 1, 1.15, 1.3]
export const DEFAULT_SPEECH_RATE = 1

export const loadVoiceName = (): string => read('speech-voice') ?? ''
export const saveVoiceName = (name: string) => write('speech-voice', name)

export function loadSpeechRate(): number {
  const n = Number(read('speech-rate'))
  return SPEECH_RATES.includes(n) ? n : DEFAULT_SPEECH_RATE
}
export const saveSpeechRate = (rate: number) => write('speech-rate', String(rate))

/** Which voice reads aloud: the natural one made by the backend when it works ('auto'), or the browser's own. */
export type SpeechEngine = 'auto' | 'browser'
export const loadSpeechEngine = (): SpeechEngine => (read('speech-engine') === 'browser' ? 'browser' : 'auto')
export const saveSpeechEngine = (engine: SpeechEngine) => write('speech-engine', engine)

/** The natural voice's id (empty = the backend's default). */
export const loadNaturalVoice = (): string => read('natural-voice') ?? ''
export const saveNaturalVoice = (id: string) => write('natural-voice', id)
