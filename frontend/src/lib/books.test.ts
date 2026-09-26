import { describe, expect, it } from 'vitest'
import type { Book } from '../api/types'
import { countByLevel, filterByLevel, formatWords, readingStatus, sentenceAt, splitSentences, tokenize } from './books'

const book = (level: Book['level']) => ({ level })

describe('levels', () => {
  it('counts and filters books by level', () => {
    const list = [book('A2'), book('B1'), book('B1'), book('C1+'), book('')]
    expect(countByLevel(list)).toEqual({ 'A2': 1, 'B1': 2, 'B2': 0, 'C1+': 1 })
    expect(filterByLevel(list, 'B1')).toHaveLength(2)
    expect(filterByLevel(list, 'all')).toHaveLength(5)
    expect(filterByLevel(list, 'B2')).toEqual([])
  })
})

describe('formatWords', () => {
  it('uses 萬 for big books', () => {
    expect(formatWords(820)).toBe('820 字')
    expect(formatWords(26382)).toBe('2.6 萬字')
    expect(formatWords(160988)).toBe('16 萬字')
  })
})

describe('readingStatus', () => {
  it('says where the reader is', () => {
    expect(readingStatus({ progress_percent: 0, last_chapter: 0, chapter_count: 12 })).toBe('尚未開始')
    expect(readingStatus({ progress_percent: 42, last_chapter: 4, chapter_count: 12 })).toBe('讀到第 5 / 12 章 · 42%')
    expect(readingStatus({ progress_percent: 100, last_chapter: 11, chapter_count: 12 })).toBe('已讀完')
  })
})

describe('tokenize', () => {
  it('keeps every character: words and the spaces between them', () => {
    const text = '“Well,”  said Alice — “it is.”'
    const parts = tokenize(text)
    expect(parts.map((p) => p.text).join('')).toBe(text)
    expect(parts.filter((p) => p.word).map((p) => p.text)).toEqual(['“Well,”', 'said', 'Alice', '—', '“it', 'is.”'])
    expect(parts.filter((p) => !p.word).every((p) => /^\s+$/.test(p.text))).toBe(true)
  })
  it('handles empty text', () => {
    expect(tokenize('')).toEqual([])
  })
})

describe('sentenceAt', () => {
  const paragraph = 'Alice was tired. She looked at her sister! “What is the use?” thought Alice.'
  it('finds the sentence around a character position', () => {
    expect(sentenceAt(paragraph, 0)).toBe('Alice was tired.')
    expect(sentenceAt(paragraph, paragraph.indexOf('sister'))).toBe('She looked at her sister!')
    expect(sentenceAt(paragraph, paragraph.indexOf('thought'))).toBe('“What is the use?” thought Alice.')
  })
  it('falls back to the whole paragraph when there is no punctuation', () => {
    expect(sentenceAt('no punctuation here', 5)).toBe('no punctuation here')
  })
})

describe('splitSentences', () => {
  it('keeps every character, so the pieces add up to the text', () => {
    const text = 'Alice was tired. She looked at her sister! “What is the use?” thought Alice. No end here'
    expect(splitSentences(text).join('')).toBe(text)
    expect(splitSentences(text).map((s) => s.trim())).toEqual([
      'Alice was tired.', 'She looked at her sister!', '“What is the use?” thought Alice.', 'No end here',
    ])
  })
  it('does not break in the middle of a number or after a lowercase word', () => {
    expect(splitSentences('It cost 3.5 dollars, e.g. a lot. Then it ended.').map((s) => s.trim())).toEqual([
      'It cost 3.5 dollars, e.g. a lot.', 'Then it ended.',
    ])
  })
  it('handles empty text and text without punctuation', () => {
    expect(splitSentences('')).toEqual([])
    expect(splitSentences('just words')).toEqual(['just words'])
  })
})
