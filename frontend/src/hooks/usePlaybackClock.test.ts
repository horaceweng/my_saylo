import { describe, expect, it } from 'vitest'
import type { Segment } from '../api/types'
import { computeClock, findIndex, loopSeekTarget, resolveFrame } from './usePlaybackClock'

const seg = (idx: number, start: number, end: number, words: [string, number, number][]): Segment => ({
  id: idx, idx, start, end, text: words.map((w) => w[0]).join(' '), translation: '',
  words: words.map(([text, s, e]) => ({ text, start: s, end: e })),
})
const segments = [
  seg(0, 1, 3, [['Hello', 1, 1.5], ['there.', 1.6, 3]]),
  seg(1, 5, 8, [['How', 5, 5.4], ['are', 5.5, 5.8], ['you?', 6, 8]]),
]

describe('findIndex', () => {
  it('returns the last start <= t', () => {
    expect(findIndex([1, 5, 9], 0.5)).toBe(-1)
    expect(findIndex([1, 5, 9], 1)).toBe(0)
    expect(findIndex([1, 5, 9], 8.99)).toBe(1)
    expect(findIndex([1, 5, 9], 100)).toBe(2)
    expect(findIndex([], 3)).toBe(-1)
  })
})

describe('computeClock', () => {
  it('is idle before the first sentence', () => {
    expect(computeClock(segments, 0.3)).toEqual({ segIdx: -1, wordIdx: -1 })
  })
  it('follows the current word', () => {
    expect(computeClock(segments, 1.2)).toEqual({ segIdx: 0, wordIdx: 0 })
    expect(computeClock(segments, 2)).toEqual({ segIdx: 0, wordIdx: 1 })
    expect(computeClock(segments, 5.6)).toEqual({ segIdx: 1, wordIdx: 1 })
  })
  it('keeps the last word lit during a short gap, then goes idle', () => {
    expect(computeClock(segments, 4)).toEqual({ segIdx: 0, wordIdx: 1 })
    expect(computeClock(segments, 4.6)).toEqual({ segIdx: -1, wordIdx: -1 })
  })
  it('goes idle after the last sentence', () => {
    expect(computeClock(segments, 20)).toEqual({ segIdx: -1, wordIdx: -1 })
  })
})

describe('loopSeekTarget', () => {
  it('does nothing when not looping or still inside the sentence', () => {
    expect(loopSeekTarget(segments, null, 9)).toBeNull()
    expect(loopSeekTarget(segments, 1, 6)).toBeNull()
  })
  it('jumps back to the start when the sentence ends', () => {
    expect(loopSeekTarget(segments, 1, 8)).toBe(5)
    expect(loopSeekTarget(segments, 1, 8.3)).toBe(5)
  })
  it('pulls the player back if the user seeks far before the sentence', () => {
    expect(loopSeekTarget(segments, 1, 1)).toBe(5)
    expect(loopSeekTarget(segments, 1, 4.6)).toBeNull() // within the 0.5s tolerance
  })
})

describe('resolveFrame', () => {
  // Back-to-back sentences: 1 ends at 8 exactly where 2 starts.
  const back2back = [seg(0, 1, 3, [['a', 1, 3]]), seg(1, 5, 8, [['b', 5, 8]]), seg(2, 8, 12, [['c', 8, 12]])]

  it('stays on the looped sentence at the moment the loop wraps', () => {
    // t has just reached the end of sentence 1, which is also the start of sentence 2
    const frame = resolveFrame(back2back, 1, 8)
    expect(frame.jumpTo).toBe(5)
    expect(frame.clock.segIdx).toBe(1) // not 2
  })
  it('behaves like computeClock when nothing is looping', () => {
    expect(resolveFrame(back2back, null, 8)).toEqual({ jumpTo: null, clock: computeClock(back2back, 8) })
    expect(resolveFrame(back2back, null, 8).clock.segIdx).toBe(2)
  })
  it('does not change anything while playback is inside the looped sentence', () => {
    expect(resolveFrame(back2back, 1, 6)).toEqual({ jumpTo: null, clock: computeClock(back2back, 6) })
  })
})
