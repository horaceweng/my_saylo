import { describe, expect, it } from 'vitest'
import { createAudioAdapter, type AudioLike } from './AudioPlayer'

const fakeAudio = (over: Partial<AudioLike> = {}) => {
  const log: string[] = []
  const el: AudioLike = {
    currentTime: 0, playbackRate: 1, paused: true, ended: false,
    play() { log.push('play'); el.paused = false },
    pause() { log.push('pause'); el.paused = true },
    ...over,
  }
  return { el, log }
}

describe('createAudioAdapter', () => {
  it('plays, pauses and reports whether it is playing', () => {
    const { el, log } = fakeAudio()
    const adapter = createAudioAdapter(el)
    expect(adapter.isPlaying()).toBe(false)
    adapter.play()
    expect(adapter.isPlaying()).toBe(true)
    adapter.pause()
    expect(log).toEqual(['play', 'pause'])
    expect(adapter.isPlaying()).toBe(false)
  })

  it('is not "playing" once the audio has ended', () => {
    const { el } = fakeAudio({ paused: false, ended: true })
    expect(createAudioAdapter(el).isPlaying()).toBe(false)
  })

  it('seeks, reads the time and changes the speed', () => {
    const { el } = fakeAudio()
    const adapter = createAudioAdapter(el)
    adapter.seek(42.5)
    expect(adapter.getCurrentTime()).toBe(42.5)
    adapter.seek(-3)
    expect(el.currentTime).toBe(0)
    adapter.setRate(0.75)
    expect(el.playbackRate).toBe(0.75)
  })

  it('does not fail when the browser refuses to play', async () => {
    const { el } = fakeAudio({ play: () => Promise.reject(new Error('NotAllowedError')) })
    expect(() => createAudioAdapter(el).play()).not.toThrow()
    await new Promise((r) => setTimeout(r, 0)) // a rejected promise nobody handled would fail the test run
  })
})
