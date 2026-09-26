import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { SavedPhrase } from '../api/types'
import { mediaPath } from '../lib/mediaStatus'

export default function Phrases() {
  const [items, setItems] = useState<SavedPhrase[] | null>(null)
  const [q, setQ] = useState('')
  const [error, setError] = useState('')
  const [due, setDue] = useState(0)

  useEffect(() => {
    const t = setTimeout(() => api.listPhrases(q).then(setItems).catch((e) => setError(e.message)), 200)
    return () => clearTimeout(t)
  }, [q])

  useEffect(() => { api.reviewQueue(1).then((r) => setDue(r.due_count)).catch(() => undefined) }, [])

  const remove = async (id: number) => {
    await api.deletePhrase(id)
    setItems((list) => list?.filter((p) => p.id !== id) ?? null)
  }

  return (
    <main className="mx-auto max-w-3xl px-4 py-8">
      <div className="mb-6 flex items-center gap-3">
        <h1 className="text-2xl font-bold">片語庫</h1>
        {items && items.length > 0 && (
          <Link to="/phrases/review" className="ml-auto rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500">
            開始複習{due > 0 ? `（${due} 個到期）` : ''}
          </Link>
        )}
      </div>
      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="搜尋片語或翻譯"
        className="mb-6 w-full rounded-xl border border-slate-300 bg-white px-4 py-2.5 outline-none focus:border-indigo-500 dark:border-slate-600 dark:bg-slate-800"
      />
      {error && <p className="rounded-lg bg-rose-50 p-3 text-rose-600 dark:bg-rose-500/10">{error}</p>}
      {!items && !error && <p className="py-12 text-center text-slate-400">載入中…</p>}
      {items?.length === 0 && <p className="py-12 text-center text-slate-400">{q ? '沒有符合的片語' : '還沒有存任何片語。播放影片時，點「⭐ 存片語」就會出現在這裡'}</p>}
      <ul className="space-y-3">
        {items?.map((p) => (
          <li key={p.id} className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-800">
            <div className="flex items-start gap-3">
              <div className="flex-1">
                <p className="text-lg font-medium">{p.text}</p>
                {p.translation && <p className="text-slate-500">{p.translation}</p>}
                {p.context_sentence && p.context_sentence !== p.text && (
                  <p className="mt-2 border-l-2 border-slate-300 pl-3 text-sm text-slate-500 dark:border-slate-600">{p.context_sentence}</p>
                )}
              </div>
              <button onClick={() => remove(p.id)} className="text-sm text-slate-400 hover:text-rose-500">刪除</button>
            </div>
            {p.source_id && (
              <Link to={mediaPath({ id: p.source_id, kind: p.source_kind }, p.source_kind === 'book' || p.source_kind === 'news' ? p.timestamp : Math.max(0, p.timestamp - 1))} className="mt-2 inline-block text-sm text-indigo-600 hover:underline">
                {p.source_kind === 'book' || p.source_kind === 'news'
                  ? p.source_kind === 'news' ? '📰 回到文章' : '📖 回到書中'
                  : `▶ 回到${p.source_kind === 'podcast' ? '這集' : '影片'} ${Math.floor(p.timestamp / 60)}:${String(Math.floor(p.timestamp % 60)).padStart(2, '0')}`}
              </Link>
            )}
          </li>
        ))}
      </ul>
    </main>
  )
}
