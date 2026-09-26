import { cleanWord } from './TranscriptView'
import { tokenize } from '../lib/books'
import { endsSentence, looksLikeName, wordKey } from '../lib/wordMarks'

export interface TranslationState {
  status: 'idle' | 'loading' | 'done' | 'error'
  text: string
  visible: boolean
  error?: string
}

interface Props {
  idx: number
  text: string
  translation: TranslationState
  onWordClick: (word: string, offset: number) => void
  onTranslate: () => void
  onExplain: () => void
  /** Start reading aloud from this paragraph (no button when reading is not supported). */
  onRead?: () => void
  /** The part being read aloud right now, if it is in this paragraph: the piece, and the word inside it. */
  spoken?: { from: number; to: number; char: number | null } | null
  /** Extra classes for a word (its difficulty underline, or a background if it was looked up). */
  wordClass?: (key: string, isName: boolean) => string
}

/** One paragraph of a book: readable text with clickable words, a translate button and an explain button. */
export default function BookParagraph({ idx, text, translation, onWordClick, onTranslate, onExplain, onRead, spoken, wordClass }: Props) {
  let offset = 0
  let sentenceStart = true
  const shown = translation.visible && (translation.status === 'done' || translation.status === 'loading')
  const label = translation.status === 'loading' ? '翻譯中…' : translation.visible ? '隱藏翻譯' : '翻譯'

  return (
    <article data-paragraph={idx} data-reading={spoken ? true : undefined} className={`group mb-5 ${spoken ? '-ml-3 border-l-2 border-amber-400 pl-[10px]' : ''}`}>
      <p className="font-serif text-[1.15rem] leading-8" data-paragraph-text>
        {tokenize(text).map((part, i) => {
          const start = offset
          offset += part.text.length
          if (!part.word) return part.text
          const isName = looksLikeName(part.text, sentenceStart)
          sentenceStart = endsSentence(part.text)
          // While reading aloud: the sentence being spoken is tinted, the word being spoken more strongly
          const end = start + part.text.length
          const current = spoken && spoken.char !== null && start <= spoken.char && spoken.char < end
          const inPiece = spoken && start >= spoken.from && start < spoken.to
          return (
            <span
              key={i}
              onClick={() => { const w = cleanWord(part.text); if (w) onWordClick(w, start) }}
              style={current ? { backgroundColor: 'rgba(251,191,36,.6)' } : inPiece ? { backgroundColor: 'rgba(251,191,36,.2)' } : undefined}
              data-speaking={current ? 'word' : undefined}
              className={`cursor-pointer rounded hover:bg-amber-200/70 dark:hover:bg-amber-400/30 ${wordClass?.(wordKey(part.text), isName) ?? ''}`}
            >
              {part.text}
            </span>
          )
        })}
      </p>
      {shown && (
        <p className={`mt-1 border-l-2 border-indigo-300 pl-3 text-[15px] text-slate-600 dark:border-indigo-500/60 dark:text-slate-300 ${translation.status === 'loading' ? 'animate-pulse' : ''}`} data-translation>
          {translation.text || '翻譯中…'}
        </p>
      )}
      {translation.status === 'error' && <p role="alert" className="mt-1 text-sm text-rose-500">{translation.error}</p>}
      <div className="mt-1 flex gap-2 text-sm opacity-60 transition-opacity focus-within:opacity-100 group-hover:opacity-100">
        <button onClick={onTranslate} className="rounded-md border border-slate-300 px-2 py-0.5 hover:bg-slate-100 dark:border-slate-600 dark:hover:bg-slate-800" data-action="translate">
          {label}
        </button>
        {onRead && (
          <button onClick={onRead} className="rounded-md border border-slate-300 px-2 py-0.5 hover:bg-slate-100 dark:border-slate-600 dark:hover:bg-slate-800" data-action="read">
            🔊 從這裡朗讀
          </button>
        )}
        <button onClick={onExplain} className="rounded-md border border-slate-300 px-2 py-0.5 hover:bg-slate-100 dark:border-slate-600 dark:hover:bg-slate-800" data-action="explain">
          💡 AI 說明
        </button>
      </div>
    </article>
  )
}
