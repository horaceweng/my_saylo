import { describe, expect, it } from 'vitest'
import type { MediaDetail, MediaUpdates, Segment } from '../api/types'
import { firstUntranslated, mergeUpdates } from './mediaUpdates'

const seg = (idx: number, translation = ''): Segment => ({ id: idx, idx, start: idx * 5, end: idx * 5 + 4, text: `s${idx}`, translation, words: [] })

const base = (segments: Segment[]): MediaDetail => ({
  id: 1, kind: 'video', source_url: '', external_id: '', title: 'T', thumbnail: '', duration: 600, status: 'transcribing', progress: 20, error: '',
  transcribed: false, level: '', sentence_count: segments.length, translated_count: segments.filter((s) => s.translation).length, covered_until: 0, playable: false, segments,
})

const updates = (over: Partial<MediaUpdates> = {}): MediaUpdates => {
  const { segments: _ignored, ...meta } = base([])
  return { ...meta, new_segments: [], translations: {}, ...over }
}

describe('mergeUpdates', () => {
  it('appends sentences that appeared and keeps the order', () => {
    const merged = mergeUpdates(base([seg(0), seg(1)]), updates({ new_segments: [seg(2), seg(3)] }))
    expect(merged.segments.map((s) => s.idx)).toEqual([0, 1, 2, 3])
  })

  it('fills in translations that arrived, without touching the ones already shown', () => {
    const merged = mergeUpdates(base([seg(0, '甲'), seg(1), seg(2)]), updates({ translations: { '0': '別的', '2': '丙' } }))
    expect(merged.segments.map((s) => s.translation)).toEqual(['甲', '', '丙'])
  })

  it('takes the new status and progress numbers', () => {
    const merged = mergeUpdates(base([seg(0)]), updates({ status: 'translating', progress: 77, playable: true, transcribed: true, covered_until: 590 }))
    expect(merged).toMatchObject({ status: 'translating', progress: 77, playable: true, transcribed: true, covered_until: 590 })
  })

  it('keeps the same segments array when only progress changed, so nothing restarts for it', () => {
    const prev = base([seg(0, '甲'), seg(1)])
    const merged = mergeUpdates(prev, updates({ progress: 55 }))
    expect(merged.segments).toBe(prev.segments)
    expect(merged.progress).toBe(55)
  })

  it('does not add a sentence twice if the server repeats one', () => {
    const merged = mergeUpdates(base([seg(0), seg(1)]), updates({ new_segments: [seg(1), seg(2)] }))
    expect(merged.segments.map((s) => s.idx)).toEqual([0, 1, 2])
  })

  it('ignores translations for sentences it does not have', () => {
    const merged = mergeUpdates(base([seg(0)]), updates({ translations: { '9': '遠' } }))
    expect(merged.segments.map((s) => s.translation)).toEqual([''])
  })
})

describe('firstUntranslated', () => {
  it('finds the first gap, or the end', () => {
    expect(firstUntranslated([seg(0, 'a'), seg(1), seg(2, 'c')])).toBe(1)
    expect(firstUntranslated([seg(0, 'a'), seg(1, 'b')])).toBe(2)
    expect(firstUntranslated([])).toBe(0)
  })
})
