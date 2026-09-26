import { useState } from 'react'
import type { Segment } from '../api/types'

interface Props {
  seg: Segment
  looping: boolean
  onExplain: () => void
  onToggleLoop: () => void
  onShadow: () => void
  onSave: (text: string) => Promise<void>
}

const btn = 'rounded-lg border px-2.5 py-1 text-sm transition-colors'
const idle = 'border-slate-300 hover:bg-white dark:border-slate-600 dark:hover:bg-slate-700'

export default function SentenceToolbar({ seg, looping, onExplain, onToggleLoop, onShadow, onSave }: Props) {
  const [saved, setSaved] = useState(false)

  const save = async () => {
    // If the learner selected part of the transcript, save that phrase; otherwise the whole sentence.
    const sel = window.getSelection()?.toString().trim()
    await onSave(sel && seg.text.includes(sel.split(/\s+/)[0]) ? sel : seg.text)
    setSaved(true)
    setTimeout(() => setSaved(false), 1500)
  }
  // mousedown would clear the text selection before the click handler reads it
  const keepSelection = (e: React.MouseEvent) => e.preventDefault()

  return (
    <div className="mt-2 flex flex-wrap gap-2" onMouseDown={keepSelection}>
      <button className={`${btn} ${idle}`} onClick={onExplain}>💡 AI 說明</button>
      <button
        className={`${btn} ${looping ? 'border-indigo-500 bg-indigo-500 text-white' : idle}`}
        onClick={onToggleLoop}
        aria-pressed={looping}
      >
        🔁 {looping ? '循環中' : '循環'}
      </button>
      <button className={`${btn} ${idle}`} onClick={save}>{saved ? '已儲存 ✓' : '⭐ 存片語'}</button>
      <button className={`${btn} ${idle}`} onClick={onShadow}>🎙 Shadowing</button>
    </div>
  )
}
