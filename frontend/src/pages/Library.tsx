import { useCallback, useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import type { Book, BookLevel, GutenbergResult, PodcastChannel, PodcastEpisode, PodcastLookup, PodcastShow } from '../api/types'
import BookCard from '../components/BookCard'
import MediaCard from '../components/MediaCard'
import { useMediaList } from '../hooks/useMediaList'
import { LEVELS, countByLevel, filterByLevel } from '../lib/books'
import { formatDuration } from '../lib/mediaStatus'

const EPISODES_SHOWN = 20
const CHANNEL_KEY = 'podcast-channel'

function rememberedChannel(): number | null {
  try {
    const n = Number(localStorage.getItem(CHANNEL_KEY))
    return Number.isInteger(n) && n > 0 ? n : null
  } catch {
    return null
  }
}

export default function Library() {
  const [params, setParams] = useSearchParams()
  const tab = params.get('tab') === 'book' ? 'book' : 'podcast'
  const tabs = [['book', '📚 書'], ['podcast', '🎧 Podcast']] as const

  return (
    <main className="mx-auto max-w-4xl px-4 py-8">
      <h1 className="mb-4 text-2xl font-bold">書籍</h1>
      <div role="tablist" className="mb-6 flex gap-1 border-b border-slate-200 dark:border-slate-700">
        {tabs.map(([value, label]) => (
          <button
            key={value}
            role="tab"
            aria-selected={tab === value}
            onClick={() => setParams({ tab: value })}
            className={`-mb-px border-b-2 px-4 py-2 text-sm font-medium ${tab === value ? 'border-indigo-600 text-indigo-600' : 'border-transparent text-slate-500 hover:text-slate-800 dark:hover:text-slate-200'}`}
          >
            {label}
          </button>
        ))}
      </div>
      {tab === 'podcast' ? <PodcastTab /> : <BookTab />}
    </main>
  )
}

function PodcastTab() {
  const { items, error: listError, refresh } = useMediaList('podcast')
  const [url, setUrl] = useState('')
  const [looking, setLooking] = useState(false)
  const [result, setResult] = useState<PodcastLookup | null>(null)
  const [channels, setChannels] = useState<PodcastChannel[] | null>(null)
  const [channelId, setChannelId] = useState<number | null>(rememberedChannel)
  const [channelShow, setChannelShow] = useState<PodcastShow | null>(null)
  const [loadingChannel, setLoadingChannel] = useState(false)
  const [following, setFollowing] = useState(false)
  const [level, setLevel] = useState<BookLevel | 'all'>('all')
  const [error, setError] = useState('')
  const [showAll, setShowAll] = useState(false)
  const [busyUrls, setBusyUrls] = useState<string[]>([])
  const [uploading, setUploading] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)
  const loaded = new Set(items?.map((m) => m.source_url))
  const counts = countByLevel(items ?? [])
  const shown = filterByLevel(items ?? [], level)
  // What the episode list shows: a link just looked up, or else the selected channel
  const currentChannel = result === null ? channels?.find((c) => c.id === channelId) ?? null : null
  const show: PodcastShow | null = result?.type === 'feed' ? result : currentChannel ? channelShow : null

  useEffect(() => {
    api.listChannels().then(setChannels).catch((e: Error) => setError(e.message))
  }, [])

  // Select a channel once the list is known: the remembered one, or the first.
  useEffect(() => {
    if (!channels || channels.length === 0) return
    if (channelId === null || !channels.some((c) => c.id === channelId)) setChannelId(channels[0].id)
  }, [channels, channelId])

  // The selected channel's latest episodes are read from its feed each time
  useEffect(() => {
    if (channelId === null) return
    try { localStorage.setItem(CHANNEL_KEY, String(channelId)) } catch { /* not remembered */ }
    let stale = false
    setLoadingChannel(true); setChannelShow(null)
    api.channelEpisodes(channelId)
      .then((show) => !stale && setChannelShow(show))
      .catch((e: Error) => !stale && setError(e.message))
      .finally(() => !stale && setLoadingChannel(false))
    return () => { stale = true }
  }, [channelId])

  const pickChannel = (id: number) => { setChannelId(id); setResult(null); setShowAll(false) }

  const follow = async (feedUrl: string) => {
    setFollowing(true); setError('')
    try {
      const channel = await api.followChannel(feedUrl)
      setChannels((list) => (list?.some((c) => c.id === channel.id) ? list : [...(list ?? []), channel]))
      setResult(null); setUrl('')
      pickChannel(channel.id)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setFollowing(false)
    }
  }

  const unfollow = async (channel: PodcastChannel) => {
    try {
      await api.unfollowChannel(channel.id)
      setChannels((list) => list?.filter((c) => c.id !== channel.id) ?? null)
      setChannelShow(null)
      setChannelId(null)
    } catch (err) {
      setError((err as Error).message)
    }
  }

  const lookUp = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!url.trim()) return
    setLooking(true); setError(''); setResult(null); setShowAll(false)
    try {
      setResult(await api.lookUpPodcast(url.trim()))
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLooking(false)
    }
  }

  const add = async (episode: { audio_url: string; title?: string; thumbnail?: string; duration?: number }) => {
    setBusyUrls((u) => [...u, episode.audio_url]); setError('')
    try {
      await api.addPodcast(episode)
      await refresh()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusyUrls((u) => u.filter((x) => x !== episode.audio_url))
    }
  }

  const upload = async (file: File | undefined) => {
    if (!file) return
    setUploading(true); setError('')
    try {
      await api.uploadPodcast(file)
      await refresh()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setUploading(false)
      if (fileInput.current) fileInput.current.value = ''
    }
  }

  const button = (audio: string, episode: PodcastEpisode | null, image = '') => {
    const done = loaded.has(audio)
    const busy = busyUrls.includes(audio)
    return (
      <button
        onClick={() => add({ audio_url: audio, title: episode?.title, thumbnail: image, duration: episode?.duration })}
        disabled={done || busy}
        className="shrink-0 rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-500 disabled:bg-slate-300 disabled:text-slate-500 dark:disabled:bg-slate-700"
      >
        {done ? '已載入' : busy ? '加入中…' : '載入'}
      </button>
    )
  }

  return (
    <div>
      {channels && channels.length > 0 && (
        <section className="mb-5" aria-label="我追蹤的節目">
          <h2 className="mb-2 text-sm font-medium text-slate-500">我追蹤的節目</h2>
          <div className="flex flex-wrap gap-2">
            {channels.map((c) => (
              <button
                key={c.id}
                onClick={() => pickChannel(c.id)}
                aria-pressed={c.id === channelId && result === null}
                className={`flex items-center gap-2 rounded-full py-1 pl-1 pr-3 text-sm ${c.id === channelId && result === null ? 'bg-indigo-600 text-white' : 'bg-slate-200 hover:bg-slate-300 dark:bg-slate-700 dark:hover:bg-slate-600'}`}
              >
                {c.image ? <img src={c.image} alt="" className="h-6 w-6 rounded-full object-cover" /> : <span className="pl-2" />}
                {c.title}
              </button>
            ))}
          </div>
        </section>
      )}
      <form onSubmit={lookUp} className="mb-2 flex gap-2">
        <input
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="貼上 Podcast RSS 網址，或 mp3 音檔網址"
          className="flex-1 rounded-xl border border-slate-300 bg-white px-4 py-2.5 outline-none focus:border-indigo-500 dark:border-slate-600 dark:bg-slate-800"
        />
        <button disabled={looking} className="rounded-xl bg-indigo-600 px-5 py-2.5 font-medium text-white hover:bg-indigo-500 disabled:opacity-60">
          {looking ? '查詢中…' : '查詢'}
        </button>
      </form>
      <div className="mb-6 flex flex-wrap items-center gap-3 text-sm text-slate-500">
        <span>或者</span>
        <input ref={fileInput} type="file" accept="audio/*,.mp3,.m4a,.wav,.ogg,.flac" hidden onChange={(e) => upload(e.target.files?.[0])} />
        <button onClick={() => fileInput.current?.click()} disabled={uploading} className="rounded-lg border border-slate-300 px-3 py-1.5 hover:bg-slate-100 disabled:opacity-60 dark:border-slate-600 dark:hover:bg-slate-800">
          {uploading ? '上傳中…' : '📁 上傳音檔'}
        </button>
        <span>例如 BBC 的 6 Minute English：https://podcasts.files.bbci.co.uk/p02pc9tn.rss</span>
      </div>

      {(error || listError) && <p role="alert" className="mb-4 rounded-lg bg-rose-50 p-3 text-rose-600 dark:bg-rose-500/10">{error || listError}</p>}

      {result?.type === 'audio' && (
        <div className="mb-6 flex items-center gap-3 rounded-xl border border-slate-200 p-3 dark:border-slate-700">
          <span className="flex-1 truncate text-sm">這是一個音檔連結：{result.audio_url}</span>
          {button(result.audio_url, null)}
        </div>
      )}

      {show && (
        <section className="mb-8" aria-label="集數">
          <div className="mb-3 flex items-center gap-3">
            {show.image && <img src={show.image} alt="" className="h-14 w-14 rounded-lg object-cover" />}
            <div className="min-w-0 flex-1">
              <h2 className="font-semibold">{show.title}</h2>
              <p className="text-sm text-slate-500">共 {show.episodes.length} 集，選一集載入</p>
            </div>
            {result?.type === 'feed' && (
              <button
                onClick={() => follow(url.trim())}
                disabled={following}
                className="shrink-0 rounded-lg border border-indigo-600 px-3 py-1.5 text-sm font-medium text-indigo-600 hover:bg-indigo-50 disabled:opacity-60 dark:hover:bg-indigo-500/10"
              >
                {following ? '加入中…' : '＋ 追蹤這個節目'}
              </button>
            )}
          </div>
          <ul className="divide-y divide-slate-200 rounded-xl border border-slate-200 dark:divide-slate-700 dark:border-slate-700">
            {(showAll ? show.episodes : show.episodes.slice(0, EPISODES_SHOWN)).map((ep) => (
              <li key={ep.audio_url} className="flex items-center gap-3 p-3" data-episode>
                <div className="min-w-0 flex-1">
                  <p className="truncate font-medium">{ep.title}</p>
                  <p className="text-xs text-slate-500">{[ep.published, ep.duration > 0 && formatDuration(ep.duration)].filter(Boolean).join(' · ')}</p>
                </div>
                {button(ep.audio_url, ep, show.image)}
              </li>
            ))}
          </ul>
          {!showAll && show.episodes.length > EPISODES_SHOWN && (
            <button onClick={() => setShowAll(true)} className="mt-2 text-sm text-indigo-600 hover:underline">顯示全部 {show.episodes.length} 集</button>
          )}
          {currentChannel && (
            <button onClick={() => unfollow(currentChannel)} className="mt-2 block text-sm text-slate-400 hover:text-rose-500">不再追蹤「{currentChannel.title}」</button>
          )}
        </section>
      )}
      {loadingChannel && result === null && <p className="mb-6 py-6 text-center text-slate-400">讀取最新集數中…</p>}

      <h2 className="mb-3 text-lg font-semibold">我的 Podcast</h2>
      {!items && !listError && <p className="py-8 text-center text-slate-400">載入中…</p>}
      {items?.length === 0 && <p className="py-8 text-center text-slate-400">還沒有載入任何 Podcast，貼上網址或上傳音檔開始吧</p>}
      {items && items.length > 0 && (
        <div className="mb-4 flex flex-wrap items-center gap-2">
          {(['all', ...LEVELS] as const).map((value) => (
            <button
              key={value}
              onClick={() => setLevel(value)}
              aria-pressed={level === value}
              className={`rounded-full px-3 py-1 text-sm ${level === value ? 'bg-indigo-600 text-white' : 'bg-slate-200 hover:bg-slate-300 dark:bg-slate-700 dark:hover:bg-slate-600'}`}
            >
              {value === 'all' ? `全部 ${items.length}` : `${value} ${counts[value]}`}
            </button>
          ))}
          <span className="text-xs text-slate-400">難度是估計值（生字比例＋句長），處理完才會顯示</span>
        </div>
      )}
      {items && items.length > 0 && shown.length === 0 && <p className="py-8 text-center text-slate-400">沒有 {level} 等級的 Podcast</p>}
      <div className="grid gap-4 sm:grid-cols-2">
        {shown.map((m) => <MediaCard key={m.id} media={m} onChanged={refresh} />)}
      </div>
    </div>
  )
}


function BookTab() {
  const [books, setBooks] = useState<Book[] | null>(null)
  const [level, setLevel] = useState<BookLevel | 'all'>('all')
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  const [searching, setSearching] = useState(false)
  const [results, setResults] = useState<GutenbergResult[] | null>(null)
  const [importing, setImporting] = useState<number | 'upload' | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)

  const refresh = useCallback(() => api.listBooks().then(setBooks).catch((e: Error) => setError(e.message)), [])
  useEffect(() => { void refresh() }, [refresh])

  const counts = countByLevel(books ?? [])
  const shown = filterByLevel(books ?? [], level)
  const loaded = new Set(books?.map((b) => b.source_key))

  const search = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!query.trim()) return
    setSearching(true); setError(''); setResults(null)
    try {
      setResults(await api.searchGutenberg(query.trim()))
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setSearching(false)
    }
  }

  const importFrom = async (task: () => Promise<Book>, marker: number | 'upload') => {
    setImporting(marker); setError('')
    try {
      await task()
      await refresh()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setImporting(null)
      if (fileInput.current) fileInput.current.value = ''
    }
  }

  return (
    <div>
      <form onSubmit={search} className="mb-2 flex gap-2">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="搜尋免費公版書（Project Gutenberg），例如 alice、sherlock holmes、jane austen"
          className="flex-1 rounded-xl border border-slate-300 bg-white px-4 py-2.5 outline-none focus:border-indigo-500 dark:border-slate-600 dark:bg-slate-800"
        />
        <button disabled={searching} className="rounded-xl bg-indigo-600 px-5 py-2.5 font-medium text-white hover:bg-indigo-500 disabled:opacity-60">
          {searching ? '搜尋中…' : '搜尋'}
        </button>
      </form>
      <div className="mb-6 flex flex-wrap items-center gap-3 text-sm text-slate-500">
        <span>或者</span>
        <input ref={fileInput} type="file" accept=".epub,.txt" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) void importFrom(() => api.uploadBook(f), 'upload') }} />
        <button onClick={() => fileInput.current?.click()} disabled={importing === 'upload'} className="rounded-lg border border-slate-300 px-3 py-1.5 hover:bg-slate-100 disabled:opacity-60 dark:border-slate-600 dark:hover:bg-slate-800">
          {importing === 'upload' ? '匯入並分析中…' : '📁 上傳 EPUB 或 txt'}
        </button>
      </div>

      {error && <p role="alert" className="mb-4 rounded-lg bg-rose-50 p-3 text-rose-600 dark:bg-rose-500/10">{error}</p>}

      {results && (
        <section className="mb-8" aria-label="搜尋結果">
          <h2 className="mb-2 font-semibold">搜尋結果（{results.length}）</h2>
          {results.length === 0 && <p className="text-slate-500">找不到符合的英文書，換個關鍵字試試。</p>}
          <ul className="divide-y divide-slate-200 rounded-xl border border-slate-200 dark:divide-slate-700 dark:border-slate-700">
            {results.map((r) => {
              const done = loaded.has(`gutenberg:${r.id}`)
              return (
                <li key={r.id} className="flex items-center gap-3 p-3" data-result>
                  <img src={r.cover} alt="" loading="lazy" onError={(e) => { e.currentTarget.style.visibility = 'hidden' }} className="h-14 w-10 shrink-0 rounded object-cover" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-medium">{r.title}</p>
                    <p className="truncate text-sm text-slate-500">{r.author}</p>
                  </div>
                  <button
                    onClick={() => importFrom(() => api.addGutenbergBook(r.id), r.id)}
                    disabled={done || importing !== null}
                    className="shrink-0 rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-500 disabled:bg-slate-300 disabled:text-slate-500 dark:disabled:bg-slate-700"
                  >
                    {done ? '已載入' : importing === r.id ? '下載並分析中…' : '載入'}
                  </button>
                </li>
              )
            })}
          </ul>
        </section>
      )}

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <h2 className="mr-2 text-lg font-semibold">我的書</h2>
        {(['all', ...LEVELS] as const).map((value) => (
          <button
            key={value}
            onClick={() => setLevel(value)}
            aria-pressed={level === value}
            className={`rounded-full px-3 py-1 text-sm ${level === value ? 'bg-indigo-600 text-white' : 'bg-slate-200 hover:bg-slate-300 dark:bg-slate-700 dark:hover:bg-slate-600'}`}
          >
            {value === 'all' ? `全部 ${books?.length ?? 0}` : `${value} ${counts[value]}`}
          </button>
        ))}
        <span className="text-xs text-slate-400">難度是估計值（生字比例＋句長）</span>
      </div>
      {!books && !error && <p className="py-8 text-center text-slate-400">載入中…</p>}
      {books?.length === 0 && <p className="py-8 text-center text-slate-400">還沒有書。搜尋公版書，或上傳自己的 EPUB／txt 開始吧</p>}
      {books && books.length > 0 && shown.length === 0 && <p className="py-8 text-center text-slate-400">沒有 {level} 等級的書</p>}
      <div className="grid gap-4 sm:grid-cols-2">
        {shown.map((b) => <BookCard key={b.id} book={b} onChanged={refresh} />)}
      </div>
    </div>
  )
}
