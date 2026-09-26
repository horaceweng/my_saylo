import type { Book, BookLevel } from '../api/types'

export const LEVELS: BookLevel[] = ['A2', 'B1', 'B2', 'C1+']

export const LEVEL_STYLES: Record<BookLevel, string> = {
  'A2': 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/20 dark:text-emerald-300',
  'B1': 'bg-sky-100 text-sky-700 dark:bg-sky-500/20 dark:text-sky-300',
  'B2': 'bg-amber-100 text-amber-700 dark:bg-amber-500/20 dark:text-amber-300',
  'C1+': 'bg-rose-100 text-rose-700 dark:bg-rose-500/20 dark:text-rose-300',
}

/** How many books there are at each level (for the filter buttons). */
export function countByLevel(books: Pick<Book, 'level'>[]): Record<BookLevel, number> {
  const counts: Record<BookLevel, number> = { 'A2': 0, 'B1': 0, 'B2': 0, 'C1+': 0 }
  for (const b of books) if (b.level) counts[b.level] += 1
  return counts
}

export function filterByLevel<T extends Pick<Book, 'level'>>(books: T[], level: BookLevel | 'all'): T[] {
  return level === 'all' ? books : books.filter((b) => b.level === level)
}

/** "12 萬字", "3.9 萬字", "820 字" */
export function formatWords(words: number): string {
  if (words >= 100_000) return `${Math.round(words / 10_000)} 萬字`
  if (words >= 10_000) return `${(words / 10_000).toFixed(1)} 萬字`
  return `${words} 字`
}

export function readingStatus(book: Pick<Book, 'progress_percent' | 'last_chapter' | 'chapter_count'>): string {
  if (book.progress_percent <= 0) return '尚未開始'
  if (book.progress_percent >= 99) return '已讀完'
  return `讀到第 ${book.last_chapter + 1} / ${book.chapter_count} 章 · ${book.progress_percent}%`
}

/** A paragraph as words and the spaces between them, so each word can be clicked. */
export function tokenize(text: string): { text: string; word: boolean }[] {
  return text.split(/(\s+)/).filter(Boolean).map((part) => ({ text: part, word: !/^\s+$/.test(part) }))
}

/** Split running text into sentences (pieces that together are the whole text, leading spaces included).
 * A sentence ends at . ! ? … (plus closing quotes) only when the next word starts with a capital or a digit:
 * in “What is the use?” thought Alice, the words after the question mark still belong to the sentence. */
export function splitSentences(text: string): string[] {
  const pieces: string[] = []
  let start = 0
  const end = /[.!?…]+["'”’)\]]*/g
  for (let m = end.exec(text); m; m = end.exec(text)) {
    const stop = m.index + m[0].length
    if (/^\s+["'“‘(\[]*[A-Z0-9]/.test(text.slice(stop))) {
      pieces.push(text.slice(start, stop))
      start = stop
    }
  }
  if (start < text.length) pieces.push(text.slice(start))
  return pieces
}

/** The sentence of `paragraph` that contains character position `offset` (for the word panel's context). */
export function sentenceAt(paragraph: string, offset: number): string {
  let start = 0
  for (const piece of splitSentences(paragraph)) {
    if (offset < start + piece.length) return piece.trim()
    start += piece.length
  }
  return paragraph.trim()
}
