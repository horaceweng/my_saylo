/** Colouring words by difficulty: an underline for words harder than the reader's own level, a background
 * for words already looked up or saved. Levels come from the dictionary: 0 basic, 1 CET4, 2 CET6,
 * 3 TOEFL/IELTS, 4 GRE or rare. */

export const LEVEL_NAMES = ['基礎', 'CET4', 'CET6', 'TOEFL/IELTS', 'GRE/罕用']

export const LEVEL_UNDERLINE: Record<number, string> = {
  1: 'decoration-sky-400',
  2: 'decoration-emerald-500',
  3: 'decoration-amber-500',
  4: 'decoration-rose-500',
}

/** Chips in the legend use a plain background version of the same colours. */
export const LEVEL_SWATCH: Record<number, string> = {
  1: 'bg-sky-400',
  2: 'bg-emerald-500',
  3: 'bg-amber-500',
  4: 'bg-rose-500',
}

export const SEEN_STYLE = 'rounded bg-violet-200/70 dark:bg-violet-500/30'

/** "My level" = the hardest level the reader already knows: words above it get underlined. */
export const MY_LEVEL_OPTIONS = [
  { value: 0, label: '基礎（國中）' },
  { value: 1, label: 'CET4（高中）' },
  { value: 2, label: 'CET6（大學）' },
  { value: 3, label: 'TOEFL／IELTS' },
]
export const DEFAULT_MY_LEVEL = 1

/** The form of a word used to look it up: lower case, no punctuation around it, no possessive "'s". */
export function wordKey(token: string): string {
  const t = token
    .replace(/^[^A-Za-z]+|[^A-Za-z]+$/g, '')
    .replace(/’/g, "'")
    .toLowerCase()
    .replace(/'s$/, '')
  return /^[a-z][a-z'-]*$/.test(t) ? t : ''
}

/** Does this token end a sentence (a full stop, ! or ?, perhaps followed by closing quotes)? */
export const endsSentence = (token: string): boolean => /[.!?…]["'”’)\]]*$/.test(token)

/** A capital letter in the middle of a sentence marks a name (Manchester, NATO), which is not vocabulary to learn. */
export const looksLikeName = (token: string, atSentenceStart: boolean): boolean => !atSentenceStart && /^["'“‘(\[]*[A-Z]/.test(token)

/** Every distinct word of the texts, in the form used for lookups. */
export function extractWords(texts: string[]): string[] {
  const found = new Set<string>()
  for (const text of texts) {
    for (const token of text.split(/\s+/)) {
      const key = wordKey(token)
      if (key) found.add(key)
    }
  }
  return [...found]
}

/** The classes for one word: an underline if it is harder than `myLevel`, a background if it was seen before. */
export function markClass(level: number | undefined, myLevel: number, seen: boolean): string {
  const classes: string[] = []
  if (seen) classes.push(SEEN_STYLE)
  if (level !== undefined && level > myLevel && LEVEL_UNDERLINE[level]) {
    classes.push(`underline decoration-2 underline-offset-4 ${LEVEL_UNDERLINE[level]}`)
  }
  return classes.join(' ')
}

/** The levels a legend has to explain for a given reader: those above their own level. */
export function levelsShown(myLevel: number): number[] {
  return [1, 2, 3, 4].filter((l) => l > myLevel)
}

// ---- remembered choices (per browser; the settings page will show them later) --------------

const KEY_LEVEL = 'my-level'
const KEY_ENABLED = 'word-marks-enabled'
const KEY_SEEN = 'seen-words'
const MAX_SEEN = 5000

function read(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

function write(key: string, value: string) {
  try {
    localStorage.setItem(key, value)
  } catch {
    /* the choice just is not remembered */
  }
}

export function loadMyLevel(): number {
  const n = Number(read(KEY_LEVEL))
  return Number.isInteger(n) && n >= 0 && n <= 3 && read(KEY_LEVEL) !== null ? n : DEFAULT_MY_LEVEL
}
export const saveMyLevel = (level: number) => write(KEY_LEVEL, String(level))

export const loadMarksEnabled = (): boolean => read(KEY_ENABLED) !== 'off'
export const saveMarksEnabled = (on: boolean) => write(KEY_ENABLED, on ? 'on' : 'off')

export function loadSeen(): Set<string> {
  try {
    const parsed = JSON.parse(read(KEY_SEEN) ?? '[]')
    return new Set(Array.isArray(parsed) ? parsed.filter((w) => typeof w === 'string') : [])
  } catch {
    return new Set()
  }
}
export function saveSeen(words: Set<string>) {
  write(KEY_SEEN, JSON.stringify([...words].slice(-MAX_SEEN)))
}
