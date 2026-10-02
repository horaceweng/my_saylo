import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import type { Book, BookLevel, FeedItem, NewsFeed } from '../api/types'
import BookCard from '../components/BookCard'
import { LEVELS, LEVEL_STYLES, countByLevel, filterByLevel } from '../lib/books'

export default function News() {
  const navigate = useNavigate()
  const [feeds, setFeeds] = useState<NewsFeed[] | null>(null)
  const [feedId, setFeedId] = useState<number | null>(null)
  const [items, setItems] = useState<FeedItem[] | null>(null)
  const [loadingItems, setLoadingItems] = useState(false)
  const [articles, setArticles] = useState<Book[] | null>(null)
  const [level, setLevel] = useState<BookLevel | 'all'>('all')
  const [pasted, setPasted] = useState('')
  const [importing, setImporting] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)
  const [feedUrl, setFeedUrl] = useState('')
  const [error, setError] = useState('')

  const refreshArticles = useCallback(() => api.listBooks('news').then(setArticles).catch((e: Error) => setError(e.message)), [])
  const refreshFeeds = useCallback(() => api.listFeeds().then(setFeeds).catch((e: Error) => setError(e.message)), [])
  useEffect(() => { void refreshArticles(); void refreshFeeds() }, [refreshArticles, refreshFeeds])

  // A feed's latest articles are read only when the learner opens it (nothing is open at first)
  useEffect(() => {
    if (feedId === null) { setLoadingItems(false); setItems(null); return }
    let stale = false
    setLoadingItems(true); setItems(null)
    api.feedItems(feedId)
      .then((rows) => !stale && setItems(rows))
      .catch((e: Error) => !stale && setError(e.message))
      .finally(() => !stale && setLoadingItems(false))
    return () => { stale = true }
  }, [feedId])

  // Clicking the open feed again closes its list
  const toggleFeed = (id: number) => setFeedId((prev) => (prev === id ? null : id))

  const open = async (url: string, articleId: number | null = null) => {
    if (articleId !== null) return navigate(`/news/${articleId}`)
    setImporting(url); setError('')
    try {
      const article = await api.addArticle(url)
      navigate(`/news/${article.id}`)
    } catch (e) {
      setError(`無法載入這篇文章：${(e as Error).message}`)
    } finally {
      setImporting(null)
    }
  }

  const addFeed = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!feedUrl.trim()) return
    setError('')
    try {
      const feed = await api.addFeed(feedUrl.trim())
      setFeedUrl(''); setAdding(false)
      await refreshFeeds()
      setFeedId(feed.id)
    } catch (err) {
      setError((err as Error).message)
    }
  }

  const removeFeed = async (feed: NewsFeed) => {
    if (!confirm(`移除訂閱「${feed.title}」？（已載入的文章不會被刪除）`)) return
    await api.deleteFeed(feed.id)
    setFeedId(null)
    await refreshFeeds()
  }

  const counts = countByLevel(articles ?? [])
  const shown = filterByLevel(articles ?? [], level)
  const current = feeds?.find((f) => f.id === feedId)

  return (
    <main className="mx-auto max-w-4xl px-4 py-8">
      <h1 className="mb-6 text-2xl font-bold">新聞</h1>

      <form onSubmit={(e) => { e.preventDefault(); if (pasted.trim()) void open(pasted.trim()) }} className="mb-2 flex gap-2">
        <input
          value={pasted}
          onChange={(e) => setPasted(e.target.value)}
          placeholder="貼上任何一篇英文新聞的網址"
          className="flex-1 rounded-xl border border-slate-300 bg-white px-4 py-2.5 outline-none focus:border-indigo-500 dark:border-slate-600 dark:bg-slate-800"
        />
        <button disabled={importing !== null} className="rounded-xl bg-indigo-600 px-5 py-2.5 font-medium text-white hover:bg-indigo-500 disabled:opacity-60">
          {importing === pasted.trim() ? '載入中…' : '閱讀'}
        </button>
      </form>
      <p className="mb-6 text-sm text-slate-500">會抓出文章正文、分成段落，並估計難度。需要登入或有付費牆的網站可能抓不到。</p>

      {error && <p role="alert" className="mb-4 rounded-lg bg-rose-50 p-3 text-rose-600 dark:bg-rose-500/10">{error}</p>}

      <section aria-label="訂閱" className="mb-10">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <h2 className="mr-1 text-lg font-semibold">最新文章</h2>
          {feeds?.map((f) => (
            <button
              key={f.id}
              onClick={() => toggleFeed(f.id)}
              aria-pressed={f.id === feedId}
              className={`rounded-full px-3 py-1 text-sm ${f.id === feedId ? 'bg-indigo-600 text-white' : 'bg-slate-200 hover:bg-slate-300 dark:bg-slate-700 dark:hover:bg-slate-600'}`}
            >
              {f.title}
            </button>
          ))}
          <button onClick={() => setAdding((v) => !v)} className="rounded-full border border-dashed border-slate-400 px-3 py-1 text-sm text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800">＋ 新增訂閱</button>
        </div>
        {adding && (
          <form onSubmit={addFeed} className="mb-3 flex gap-2">
            <input value={feedUrl} onChange={(e) => setFeedUrl(e.target.value)} placeholder="貼上 RSS 訂閱網址" className="flex-1 rounded-lg border border-slate-300 bg-white px-3 py-2 dark:border-slate-600 dark:bg-slate-800" />
            <button className="rounded-lg bg-indigo-600 px-4 py-2 text-white">加入</button>
          </form>
        )}
        {feeds?.length === 0 && <p className="py-4 text-slate-400">還沒有訂閱，按「＋ 新增訂閱」貼上 RSS 網址。</p>}
        {loadingItems && <p className="py-6 text-center text-slate-400">讀取最新文章中…</p>}
        {current && items && (
          <h3 className="mb-2 font-semibold">
            <button onClick={() => setFeedId(null)} aria-expanded="true" title="收起文章" className="text-left hover:text-indigo-600">
              {current.title} <span className="text-sm font-normal text-slate-400">▲ 收起</span>
            </button>
          </h3>
        )}
        {items && (
          <ul className="divide-y divide-slate-200 rounded-xl border border-slate-200 dark:divide-slate-700 dark:border-slate-700">
            {items.map((item) => (
              <li key={item.url} className="flex items-start gap-3 p-3" data-feed-item>
                <div className="min-w-0 flex-1">
                  <p className="font-medium">{item.title}</p>
                  <p className="text-xs text-slate-500">{item.published}</p>
                  {item.summary && <p className="mt-0.5 line-clamp-2 text-sm text-slate-600 dark:text-slate-400">{item.summary}</p>}
                </div>
                {item.level && <span className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${LEVEL_STYLES[item.level]}`}>{item.level}</span>}
                <button
                  onClick={() => open(item.url, item.article_id)}
                  disabled={importing !== null}
                  className="shrink-0 rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
                >
                  {importing === item.url ? '載入中…' : item.article_id ? '繼續閱讀' : '閱讀'}
                </button>
              </li>
            ))}
          </ul>
        )}
        {current && items && (
          <button onClick={() => removeFeed(current)} className="mt-2 text-sm text-slate-400 hover:text-rose-500">移除「{current.title}」這個訂閱</button>
        )}
      </section>

      <section aria-label="我的文章">
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <h2 className="mr-2 text-lg font-semibold">我讀過的文章</h2>
          {(['all', ...LEVELS] as const).map((value) => (
            <button
              key={value}
              onClick={() => setLevel(value)}
              aria-pressed={level === value}
              className={`rounded-full px-3 py-1 text-sm ${level === value ? 'bg-indigo-600 text-white' : 'bg-slate-200 hover:bg-slate-300 dark:bg-slate-700 dark:hover:bg-slate-600'}`}
            >
              {value === 'all' ? `全部 ${articles?.length ?? 0}` : `${value} ${counts[value]}`}
            </button>
          ))}
        </div>
        {!articles && !error && <p className="py-8 text-center text-slate-400">載入中…</p>}
        {articles?.length === 0 && <p className="py-8 text-center text-slate-400">還沒有文章。從上面的最新文章選一篇，或貼上網址開始吧</p>}
        <div className="grid gap-4 sm:grid-cols-2">
          {shown.map((a) => <BookCard key={a.id} book={a} onChanged={refreshArticles} />)}
        </div>
      </section>
    </main>
  )
}
