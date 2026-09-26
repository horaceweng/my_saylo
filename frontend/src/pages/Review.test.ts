import { describe, expect, it } from 'vitest'
import { nextDueText } from './Review'

const now = Date.parse('2026-01-01T00:00:00Z')
const at = (minutes: number) => new Date(now + minutes * 60000).toISOString()

describe('nextDueText', () => {
  it('is empty without a date', () => expect(nextDueText(null, now)).toBe(''))
  it('picks minutes, hours or days', () => {
    expect(nextDueText(at(0.5), now)).toBe('馬上')
    expect(nextDueText(at(10), now)).toBe('10 分鐘後')
    expect(nextDueText(at(180), now)).toBe('3 小時後')
    expect(nextDueText(at(3 * 1440), now)).toBe('3 天後')
  })
})
