import { describe, expect, it } from 'vitest'
import type { Segment } from '../api/types'
import { clamp, sentenceTarget } from './navigation'

const seg = (idx: number, start: number, end: number): Segment => ({ id: idx, idx, start, end, text: '', translation: '', words: [] })
const segments = [seg(0, 1, 3), seg(1, 5, 8), seg(2, 10, 12)]

describe('sentenceTarget', () => {
  it('next goes to the following sentence', () => {
    expect(sentenceTarget(segments, 6, 'next')).toBe(10)
    expect(sentenceTarget(segments, 0, 'next')).toBe(1) // before the first sentence
    expect(sentenceTarget(segments, 11, 'next')).toBeNull() // already on the last
  })
  it('prev goes to the sentence before the current one', () => {
    expect(sentenceTarget(segments, 11, 'prev')).toBe(5)
    expect(sentenceTarget(segments, 6, 'prev')).toBe(1)
  })
  it('prev on the first sentence restarts it; before it there is nothing', () => {
    expect(sentenceTarget(segments, 2, 'prev')).toBe(1)
    expect(sentenceTarget(segments, 0.5, 'prev')).toBeNull()
  })
  it('prev during the silence after a sentence returns to that sentence', () => {
    expect(sentenceTarget(segments, 4, 'prev')).toBe(1)
    expect(sentenceTarget(segments, 9, 'prev')).toBe(5)
  })
  it('handles no segments', () => {
    expect(sentenceTarget([], 3, 'next')).toBeNull()
  })
})

describe('clamp', () => {
  it('keeps values in range', () => {
    expect(clamp(-3, 0, 100)).toBe(0)
    expect(clamp(120, 0, 100)).toBe(100)
    expect(clamp(50, 0, 100)).toBe(50)
  })
})
