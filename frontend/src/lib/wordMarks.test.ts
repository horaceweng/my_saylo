import { beforeEach, describe, expect, it, vi } from 'vitest'
import { DEFAULT_MY_LEVEL, endsSentence, extractWords, levelsShown, looksLikeName, loadMarksEnabled, loadMyLevel, loadSeen, markClass, saveMarksEnabled, saveMyLevel, saveSeen, wordKey } from './wordMarks'

describe('wordKey', () => {
  it('reduces a token to the word to look up', () => {
    expect(wordKey('“Curiouser,”')).toBe('curiouser')
    expect(wordKey('Alice’s')).toBe('alice')
    expect(wordKey("don't")).toBe("don't")
    expect(wordKey('DON’T')).toBe("don't")
    expect(wordKey('well-known')).toBe('well-known')
  })
  it('gives nothing for tokens that are not words', () => {
    for (const t of ['—', '12', '3.5', '$40', '', '…', '2026']) expect(wordKey(t)).toBe('')
  })
})

describe('extractWords', () => {
  it('lists each distinct word once', () => {
    expect(extractWords(['The cat, the DOG.', 'A cat!']).sort()).toEqual(['a', 'cat', 'dog', 'the'])
    expect(extractWords([])).toEqual([])
  })
})

describe('markClass', () => {
  it('underlines only the words harder than the reader\'s level, in that level\'s colour', () => {
    expect(markClass(undefined, 1, false)).toBe('')
    expect(markClass(0, 1, false)).toBe('')
    expect(markClass(1, 1, false)).toBe('')  // as hard as the reader's own level: not marked
    expect(markClass(2, 1, false)).toContain('decoration-emerald-500')
    expect(markClass(3, 1, false)).toContain('decoration-amber-500')
    expect(markClass(4, 1, false)).toContain('decoration-rose-500')
    expect(markClass(1, 0, false)).toContain('decoration-sky-400')  // a beginner sees CET4 words too
  })
  it('adds a background for words already looked up, together with the underline if it applies', () => {
    expect(markClass(0, 1, true)).toContain('bg-violet')
    const both = markClass(3, 1, true)
    expect(both).toContain('bg-violet')
    expect(both).toContain('decoration-amber-500')
  })
})

describe('levelsShown', () => {
  it('lists the levels a legend must explain', () => {
    expect(levelsShown(1)).toEqual([2, 3, 4])
    expect(levelsShown(0)).toEqual([1, 2, 3, 4])
    expect(levelsShown(3)).toEqual([4])
  })
})

describe('remembered choices', () => {
  beforeEach(() => {
    const store = new Map<string, string>()  // the tests run without a browser, so localStorage is a stand-in
    vi.stubGlobal('localStorage', {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => void store.set(k, v),
      clear: () => store.clear(),
    })
  })
  it('falls back to defaults and rejects nonsense', () => {
    expect(loadMyLevel()).toBe(DEFAULT_MY_LEVEL)
    localStorage.setItem('my-level', '9')
    expect(loadMyLevel()).toBe(DEFAULT_MY_LEVEL)
    localStorage.setItem('my-level', 'abc')
    expect(loadMyLevel()).toBe(DEFAULT_MY_LEVEL)
    expect(loadMarksEnabled()).toBe(true)
    expect(loadSeen().size).toBe(0)
  })
  it('remembers level, on/off and seen words', () => {
    saveMyLevel(0)
    expect(loadMyLevel()).toBe(0)  // 0 is a real choice, not "unset"
    saveMarksEnabled(false)
    expect(loadMarksEnabled()).toBe(false)
    saveSeen(new Set(['cat', 'dog']))
    expect([...loadSeen()].sort()).toEqual(['cat', 'dog'])
  })
  it('survives corrupted storage', () => {
    localStorage.setItem('seen-words', '{not json')
    expect(loadSeen().size).toBe(0)
  })
})

describe('without any storage (private windows, blocked site data)', () => {
  it('does not throw', () => {
    vi.stubGlobal('localStorage', { getItem: () => { throw new Error('blocked') }, setItem: () => { throw new Error('blocked') } })
    expect(loadMyLevel()).toBe(DEFAULT_MY_LEVEL)
    expect(loadMarksEnabled()).toBe(true)
    expect(loadSeen().size).toBe(0)
    expect(() => { saveMyLevel(2); saveMarksEnabled(false); saveSeen(new Set(['a'])) }).not.toThrow()
  })
})

describe('names in the middle of a sentence', () => {
  it('knows where sentences end, closing quotes included', () => {
    for (const t of ['end.', 'what?', 'stop!', 'so…', 'said.”', 'done.)']) expect(endsSentence(t)).toBe(true)
    for (const t of ['comma,', 'word', 'Mr.x', '“open']) expect(endsSentence(t)).toBe(false)
  })
  it('takes a capital inside a sentence for a name, but not the first word of a sentence', () => {
    expect(looksLikeName('Manchester', false)).toBe(true)
    expect(looksLikeName('“Premier', false)).toBe(true)
    expect(looksLikeName('NATO', false)).toBe(true)
    expect(looksLikeName('Manchester', true)).toBe(false)  // "Manchester City lost." starts a sentence
    expect(looksLikeName('city', false)).toBe(false)
  })
})
