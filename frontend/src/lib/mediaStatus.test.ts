import { describe, expect, it } from 'vitest'
import type { Media } from '../api/types'
import { formatDuration, isProcessing, mediaPath, statusText } from './mediaStatus'

const media = (over: Partial<Media>): Media => ({
  id: 7, kind: 'video', source_url: '', external_id: '', title: 'T', thumbnail: '', duration: 0, status: 'ready', progress: 100, error: '',
  transcribed: true, sentence_count: 0, translated_count: 0, covered_until: 0, playable: true, ...over,
})

describe('mediaPath', () => {
  it('goes to the right study page for each kind, with an optional start time', () => {
    expect(mediaPath({ id: 7, kind: 'video' })).toBe('/videos/7')
    expect(mediaPath({ id: 7, kind: 'podcast' })).toBe('/podcasts/7')
    expect(mediaPath({ id: 7, kind: 'podcast' }, 12.5)).toBe('/podcasts/7?t=12.5')
    expect(mediaPath({ id: 3, kind: 'book' })).toBe('/books/3')
    expect(mediaPath({ id: 3, kind: 'book' }, 41)).toBe('/books/3?p=41')  // a paragraph number, not seconds
    expect(mediaPath({ id: 9, kind: 'news' })).toBe('/news/9')
    expect(mediaPath({ id: 9, kind: 'news' }, 2)).toBe('/news/9?p=2')
  })
})

describe('statusText', () => {
  it('says so when something can be opened while it is still being made', () => {
    expect(statusText(media({ status: 'transcribing', progress: 27, playable: true }))).toBe('可以開始看 · 語音轉文字 27%')
  })
  it('shows plain progress before that and a plain label at the ends', () => {
    expect(statusText(media({ status: 'transcribing', progress: 10, playable: false }))).toBe('語音轉文字 10%')
    expect(statusText(media({ status: 'ready' }))).toBe('完成')
    expect(statusText(media({ status: 'error', playable: false }))).toBe('失敗')
    expect(isProcessing(media({ status: 'translating' }))).toBe(true)
  })
})

describe('formatDuration', () => {
  it('formats minutes and hours', () => {
    expect(formatDuration(372)).toBe('6:12')
    expect(formatDuration(3723)).toBe('1:02:03')
    expect(formatDuration(0)).toBe('0:00')
    expect(formatDuration(-5)).toBe('0:00')
  })
})
