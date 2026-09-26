import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { ReviewPhrase, ReviewQueue } from '../api/types'

const GRADES = [
  { grade: 0, label: '忘了', hint: '10 分鐘後再問', style: 'bg-rose-500 hover:bg-rose-400' },
  { grade: 1, label: '有點難', hint: '較快再看到', style: 'bg-amber-500 hover:bg-amber-400' },
  { grade: 2, label: '記得', hint: '', style: 'bg-emerald-600 hover:bg-emerald-500' },
  { grade: 3, label: '很簡單', hint: '隔更久再看到', style: 'bg-sky-600 hover:bg-sky-500' },
] as const

export function nextDueText(nextDue: string | null, now = Date.now()): string {
  if (!nextDue) return ''
  const minutes = Math.round((new Date(nextDue).getTime() - now) / 60000)
  if (minutes <= 1) return '馬上'
  if (minutes < 60) return `${minutes} 分鐘後`
  if (minutes < 60 * 36) return `${Math.round(minutes / 60)} 小時後`
  return `${Math.round(minutes / 1440)} 天後`
}

export default function Review() {
  const [queue, setQueue] = useState<ReviewQueue | null>(null)
  const [cards, setCards] = useState<ReviewPhrase[]>([])
  const [revealed, setRevealed] = useState(false)
  const [done, setDone] = useState(0)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const load = () =>
    api.reviewQueue().then((q) => { setQueue(q); setCards(q.cards); setRevealed(false) }).catch((e) => setError(e.message))
  useEffect(() => { load() }, [])

  const answer = async (grade: 0 | 1 | 2 | 3) => {
    const card = cards[0]
    setBusy(true); setError('')
    try {
      await api.reviewPhrase(card.id, grade)
      setDone((n) => n + 1)
      setCards((list) => list.slice(1))
      setRevealed(false)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const card = cards[0]
  // once this batch is finished, ask again: a forgotten card comes back after 10 minutes, and there may be more waiting
  const finished = queue && !card

  return (
    <main className="mx-auto max-w-xl px-4 py-8">
      <div className="mb-6 flex items-center gap-3">
        <h1 className="text-2xl font-bold">複習片語</h1>
        <Link to="/phrases" className="ml-auto text-sm text-indigo-600 hover:underline">← 片語庫</Link>
      </div>
      {error && <p className="mb-4 rounded-lg bg-rose-50 p-3 text-rose-600 dark:bg-rose-500/10">{error}</p>}
      {!queue && !error && <p className="py-12 text-center text-slate-400">載入中…</p>}

      {queue && queue.total === 0 && (
        <p className="py-12 text-center text-slate-400">片語庫還是空的。看影片或讀文章時，點「⭐ 存片語」，之後就能在這裡複習。</p>
      )}

      {finished && queue.total > 0 && (
        <div className="rounded-xl border border-slate-200 bg-white p-8 text-center dark:border-slate-700 dark:bg-slate-800">
          <p className="mb-2 text-3xl">🎉</p>
          <p className="text-lg font-medium">{done > 0 ? `這一輪複習了 ${done} 個片語` : '今天沒有需要複習的片語'}</p>
          {queue.next_due && <p className="mt-1 text-sm text-slate-500">下一個片語 {nextDueText(queue.next_due)}到期</p>}
          <button onClick={() => { setDone(0); load() }} className="mt-5 rounded-lg border border-slate-300 px-4 py-2 text-sm hover:bg-slate-100 dark:border-slate-600 dark:hover:bg-slate-700">
            再檢查一次
          </button>
        </div>
      )}

      {card && (
        <>
          <p className="mb-3 text-sm text-slate-500">還有 {cards.length} 張（共 {queue?.due_count} 張到期）</p>
          <div className="rounded-xl border border-slate-200 bg-white p-6 dark:border-slate-700 dark:bg-slate-800">
            <p className="text-center text-2xl font-semibold">{card.text}</p>
            {card.context_sentence && card.context_sentence !== card.text && (
              <p className="mt-4 border-l-2 border-slate-300 pl-3 text-sm text-slate-500 dark:border-slate-600">{card.context_sentence}</p>
            )}
            {revealed ? (
              <p className="mt-5 rounded-lg bg-indigo-50 p-4 text-center text-lg dark:bg-indigo-500/10">{card.translation || '（沒有翻譯）'}</p>
            ) : (
              <button onClick={() => setRevealed(true)} className="mt-6 w-full rounded-lg bg-indigo-600 py-3 font-medium text-white hover:bg-indigo-500">
                顯示答案
              </button>
            )}
          </div>
          {revealed && (
            <div className="mt-4 grid grid-cols-4 gap-2">
              {GRADES.map((g) => (
                <button key={g.grade} disabled={busy} onClick={() => answer(g.grade)} className={`rounded-lg px-2 py-3 text-sm font-medium text-white disabled:opacity-60 ${g.style}`} title={g.hint}>
                  {g.label}
                </button>
              ))}
            </div>
          )}
        </>
      )}
    </main>
  )
}
