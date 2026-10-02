import { describe, expect, it } from 'vitest'
import { usageLine } from './usage'

describe('usageLine', () => {
  it('shows what was used against each daily limit', () => {
    expect(usageLine({ media: 1, audio_minutes: 12.4, ai: 40 }, { media: 5, audio_minutes: 90, ai: 300 })).toBe('影片 1/5 · 音訊 12/90 分 · AI 40/300 次')
  })
  it('still works before the limits have arrived', () => {
    expect(usageLine({ media: 0, audio_minutes: 0, ai: 0 })).toBe('影片 0 · 音訊 0 分 · AI 0 次')
  })
})
