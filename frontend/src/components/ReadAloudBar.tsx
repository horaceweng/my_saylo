import { SPEECH_RATES } from '../lib/prefs'
import type { ReaderState } from '../lib/speech'

interface Props {
  state: ReaderState
  position: number  // 1-based paragraph number
  total: number
  rate: number
  /** waiting for the voice to make the sound */
  buffering?: boolean
  onRate: (rate: number) => void
  onPrev: () => void
  onNext: () => void
  onPause: () => void
  onResume: () => void
  onStop: () => void
}

const btn = 'flex h-9 min-w-9 items-center justify-center rounded-lg bg-slate-200 px-2 hover:bg-slate-300 dark:bg-slate-700 dark:hover:bg-slate-600'

/** Controls shown while the text is being read aloud. */
export default function ReadAloudBar({ state, position, total, rate, buffering, onRate, onPrev, onNext, onPause, onResume, onStop }: Props) {
  return (
    <div role="group" aria-label="朗讀控制" className="flex items-center gap-2 border-t border-slate-200 bg-white px-3 py-2 dark:border-slate-700 dark:bg-slate-900" data-read-bar>
      <button className={btn} onClick={onPrev} title="上一段" aria-label="上一段">⏮</button>
      <button
        className="flex h-10 w-12 items-center justify-center rounded-xl bg-indigo-600 text-lg text-white hover:bg-indigo-500"
        onClick={state === 'paused' ? onResume : onPause}
        title={state === 'paused' ? '繼續朗讀' : '暫停'}
        aria-label={state === 'paused' ? '繼續朗讀' : '暫停'}
      >
        {state === 'paused' ? '▶' : '⏸'}
      </button>
      <button className={btn} onClick={onNext} title="下一段" aria-label="下一段">⏭</button>
      <button className={btn} onClick={onStop} title="停止朗讀" aria-label="停止朗讀">⏹</button>
      <span className="ml-1 text-sm text-slate-500">第 {position} / {total} 段{buffering && state === 'playing' ? ' · 準備語音中…' : ''}</span>
      <label className="ml-auto flex items-center gap-1 text-sm text-slate-500">
        速度
        <select value={rate} onChange={(e) => onRate(Number(e.target.value))} className="rounded-md border border-slate-300 bg-white px-1.5 py-1 dark:border-slate-600 dark:bg-slate-800">
          {SPEECH_RATES.map((r) => <option key={r} value={r}>{r}×</option>)}
        </select>
      </label>
    </div>
  )
}
