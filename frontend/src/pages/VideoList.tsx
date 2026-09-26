import { useState } from 'react'
import { api } from '../api/client'
import MediaCard from '../components/MediaCard'
import { useMediaList } from '../hooks/useMediaList'

export default function VideoList() {
  const { items, error: listError, refresh } = useMediaList('video')
  const [url, setUrl] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const add = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!url.trim()) return
    setBusy(true); setError('')
    try {
      await api.createMedia(url.trim())
      setUrl('')
      await refresh()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="mx-auto max-w-4xl px-4 py-8">
      <h1 className="mb-6 text-2xl font-bold">影片</h1>
      <form onSubmit={add} className="mb-2 flex gap-2">
        <input
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="貼上 YouTube 網址，例如 https://youtu.be/…"
          className="flex-1 rounded-xl border border-slate-300 bg-white px-4 py-2.5 outline-none focus:border-indigo-500 dark:border-slate-600 dark:bg-slate-800"
        />
        <button disabled={busy} className="rounded-xl bg-indigo-600 px-5 py-2.5 font-medium text-white hover:bg-indigo-500 disabled:opacity-60">
          {busy ? '讀取中…' : '載入'}
        </button>
      </form>
      <p className="mb-6 text-sm text-slate-500">載入後會在背景下載音訊、轉成逐字稿並翻譯；前幾句翻譯好就可以開始看，其餘會在背景補上。</p>
      {(error || listError) && <p className="mb-4 rounded-lg bg-rose-50 p-3 text-rose-600 dark:bg-rose-500/10">{error || listError}</p>}
      {!items && !listError && <p className="py-12 text-center text-slate-400">載入中…</p>}
      {items?.length === 0 && <p className="py-12 text-center text-slate-400">還沒有影片，貼上網址開始吧</p>}
      <div className="grid gap-4 sm:grid-cols-2">
        {items?.map((m) => <MediaCard key={m.id} media={m} onChanged={refresh} />)}
      </div>
    </main>
  )
}
