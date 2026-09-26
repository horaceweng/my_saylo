import { beforeEach, describe, expect, it, vi } from 'vitest'
import { DEFAULT_SKIP_SECONDS, DEFAULT_SPEECH_RATE, loadShowTranslation, loadSkipSeconds, loadSpeechRate, loadVoiceName, saveShowTranslation, saveSkipSeconds, saveSpeechRate, saveVoiceName } from './prefs'

describe('preferences', () => {
  beforeEach(() => {
    const store = new Map<string, string>()  // no browser here: localStorage is a stand-in
    vi.stubGlobal('localStorage', {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => void store.set(k, v),
    })
  })

  it('starts with 5 seconds and translations shown', () => {
    expect(loadSkipSeconds()).toBe(DEFAULT_SKIP_SECONDS)
    expect(loadShowTranslation()).toBe(true)
  })

  it('remembers what was chosen', () => {
    saveSkipSeconds(15)
    saveShowTranslation(false)
    expect(loadSkipSeconds()).toBe(15)
    expect(loadShowTranslation()).toBe(false)
    saveShowTranslation(true)
    expect(loadShowTranslation()).toBe(true)
  })

  it('ignores a stored value that is not one of the offered choices', () => {
    localStorage.setItem('skip-seconds', '7')
    expect(loadSkipSeconds()).toBe(DEFAULT_SKIP_SECONDS)
    localStorage.setItem('skip-seconds', 'abc')
    expect(loadSkipSeconds()).toBe(DEFAULT_SKIP_SECONDS)
  })

  it('does not fail when storage is blocked', () => {
    vi.stubGlobal('localStorage', { getItem: () => { throw new Error('blocked') }, setItem: () => { throw new Error('blocked') } })
    expect(loadSkipSeconds()).toBe(DEFAULT_SKIP_SECONDS)
    expect(loadShowTranslation()).toBe(true)
    expect(() => { saveSkipSeconds(10); saveShowTranslation(false) }).not.toThrow()
  })

  it('remembers the reading voice and speed, and ignores odd speeds', () => {
    expect(loadVoiceName()).toBe('')
    expect(loadSpeechRate()).toBe(DEFAULT_SPEECH_RATE)
    saveVoiceName('Samantha'); saveSpeechRate(0.85)
    expect(loadVoiceName()).toBe('Samantha')
    expect(loadSpeechRate()).toBe(0.85)
    localStorage.setItem('speech-rate', '9')
    expect(loadSpeechRate()).toBe(DEFAULT_SPEECH_RATE)
  })
})
