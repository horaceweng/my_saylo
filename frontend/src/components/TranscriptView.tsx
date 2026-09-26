import { useEffect, useRef, type ReactNode } from 'react'
import type { Segment } from '../api/types'
import type { Clock } from '../hooks/usePlaybackClock'

interface Props {
  segments: Segment[]
  clock: Clock
  showTranslation: boolean
  /** Sentences without a translation are still being translated (not missing for good). */
  translationPending?: boolean
  autoScroll: boolean
  loopIdx: number | null
  onSeek: (seg: Segment) => void
  onWordClick: (word: string, seg: Segment) => void
  renderToolbar: (seg: Segment) => ReactNode
}

/** Strip punctuation so "world," looks up as "world". */
export function cleanWord(text: string): string {
  return text.replace(/^[^A-Za-z]+|[^A-Za-z]+$/g, '')
}

export default function TranscriptView({
  segments, clock, showTranslation, translationPending = false, autoScroll, loopIdx, onSeek, onWordClick, renderToolbar,
}: Props) {
  const container = useRef<HTMLDivElement>(null)
  const items = useRef<(HTMLDivElement | null)[]>([])

  useEffect(() => {
    if (!autoScroll || clock.segIdx < 0) return
    const box = container.current
    const el = items.current[clock.segIdx]
    if (!box || !el) return
    box.scrollTo({ top: el.offsetTop - box.clientHeight / 3, behavior: 'smooth' })
  }, [clock.segIdx, autoScroll])

  return (
    <div ref={container} data-transcript className="relative h-full overflow-y-auto pr-1">
      {segments.map((seg, i) => {
        const active = i === clock.segIdx
        return (
          <div
            key={seg.id}
            ref={(el) => { items.current[i] = el }}
            onClick={() => onSeek(seg)}
            className={`mb-2 cursor-pointer rounded-xl border p-3 transition-colors ${
              active
                ? 'border-indigo-300 bg-indigo-50 dark:border-indigo-500/50 dark:bg-indigo-500/10'
                : 'border-transparent hover:bg-slate-100 dark:hover:bg-slate-800/60'
            }`}
          >
            <p className="text-lg leading-relaxed">
              {seg.words.map((w, j) => (
                <span
                  key={j}
                  onClick={(e) => { e.stopPropagation(); onWordClick(cleanWord(w.text), seg) }}
                  className={`rounded px-0.5 hover:underline ${
                    active && j === clock.wordIdx ? 'bg-amber-300/80 text-slate-900 shadow-sm dark:bg-amber-400/70' : ''
                  }`}
                >
                  {w.text}{' '}
                </span>
              ))}
              {loopIdx === i && <span className="ml-1 text-sm text-indigo-500">🔁</span>}
            </p>
            {showTranslation && seg.translation && (
              <p className="mt-1 text-[15px] text-slate-500 dark:text-slate-400">{seg.translation}</p>
            )}
            {showTranslation && !seg.translation && translationPending && (
              <p className="mt-1 animate-pulse text-sm italic text-slate-400" data-translation-pending>翻譯中…</p>
            )}
            {active && <div onClick={(e) => e.stopPropagation()}>{renderToolbar(seg)}</div>}
          </div>
        )
      })}
    </div>
  )
}
