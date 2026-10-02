import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { api, mediaAudioUrl } from '../api/client'
import type { MediaDetail, Segment } from '../api/types'
import ExplainPanel from '../components/ExplainPanel'
import PlaybackControls from '../components/PlaybackControls'
import ProcessingBanner from '../components/ProcessingBanner'
import SentenceToolbar from '../components/SentenceToolbar'
import ShadowingModal from '../components/ShadowingModal'
import TranscriptView from '../components/TranscriptView'
import WordPanel from '../components/WordPanel'
import { loadShowTranslation } from '../lib/prefs'
import { FakePlayer } from '../components/players/FakePlayer'
import AudioPlayer from '../components/players/AudioPlayer'
import YouTubePlayer from '../components/players/YouTubePlayer'
import type { PlayerAdapter } from '../components/players/types'
import { usePlaybackClock } from '../hooks/usePlaybackClock'
import { firstUntranslated, mergeUpdates, pollInterval } from '../lib/mediaUpdates'
import { isProcessing, statusText } from '../lib/mediaStatus'

const RATES = [0.75, 1, 1.25]

/** The two neighbouring sentences, given to the model as context for an explanation. */
const contextOf = (segments: Segment[], seg: Segment) =>
  [segments[seg.idx - 1]?.text, segments[seg.idx + 1]?.text].filter(Boolean).join(' ')

/** The study page for a video or a podcast episode: transcript that follows the sound, translations,
 * AI explanations, saved phrases and shadowing. Only the player at the top differs between the two. */
export default function MediaPage() {
  const id = Number(useParams().id)
  const [query] = useSearchParams()
  const startAt = Number(query.get('t') ?? 0) || 0
  const useFake = import.meta.env.DEV && query.get('fake') === '1'
  const [media, setMedia] = useState<MediaDetail | null>(null)
  const [error, setError] = useState('')
  const [player, setPlayer] = useState<PlayerAdapter | null>(null)
  const [loopIdx, setLoopIdx] = useState<number | null>(null)
  const [rate, setRate] = useState(1)
  const [showTranslation, setShowTranslation] = useState(loadShowTranslation)
  const [autoScroll, setAutoScroll] = useState(true)
  const [word, setWord] = useState<{ text: string; seg: Segment } | null>(null)
  const [explain, setExplain] = useState<Segment | null>(null)
  const [shadow, setShadow] = useState<Segment | null>(null)

  const mediaRef = useRef<MediaDetail | null>(null)
  mediaRef.current = media

  useEffect(() => {
    let stale = false
    api.getMedia(id).then((m) => !stale && setMedia(m)).catch((e) => !stale && setError(e.message))
    return () => { stale = true }
  }, [id])

  // While the rest of the video is being prepared, keep looking: the whole record until something can be
  // opened, afterwards only what is new (sentences that appeared, translations that arrived).
  const active = !!media && media.status !== 'ready' && media.status !== 'error'
  const playable = !!media?.playable
  useEffect(() => {
    if (!active) return
    let stale = false
    const timer = setInterval(async () => {
      const current = mediaRef.current
      if (!current) return
      try {
        if (!current.playable) {
          const full = await api.getMedia(id)
          if (!stale) setMedia(full)
        } else {
          const updates = await api.getUpdates(id, current.segments.length, firstUntranslated(current.segments))
          if (!stale) setMedia((prev) => (prev ? mergeUpdates(prev, updates) : prev))
        }
      } catch {
        /* a missed poll is fine; the next one tries again */
      }
    }, pollInterval(playable))
    return () => { stale = true; clearInterval(timer) }
  }, [id, active, playable])

  const canOpen = !!media && (media.status === 'ready' || media.playable)
  useEffect(() => {
    if (useFake && canOpen) setPlayer(new FakePlayer())
  }, [useFake, canOpen])

  if (import.meta.env.DEV) (window as unknown as { __player: PlayerAdapter | null }).__player = player

  const segments = useMemo(() => media?.segments ?? [], [media?.segments])
  const clock = usePlaybackClock(player, segments, loopIdx)

  // Let the translator know where the learner is, so it works on the sentences around that point first.
  const lastFocus = useRef(-1)
  useEffect(() => {
    if (!active || clock.segIdx < 0 || clock.segIdx === lastFocus.current) return
    const timer = setTimeout(() => {
      lastFocus.current = clock.segIdx
      api.setFocus(id, clock.segIdx).catch(() => {})
    }, 800)
    return () => clearTimeout(timer)
  }, [id, active, clock.segIdx])

  const openShadow = (seg: Segment) => {
    player?.pause() // the learner is about to listen and record; the video must stay quiet
    setLoopIdx(null)
    setShadow(seg)
  }

  const retry = () => api.retryMedia(id).then(() => api.getMedia(id)).then(setMedia).catch((e) => setError(e.message))

  const togglePlay = () => (clock.playing ? player?.pause() : player?.play())

  const changeRate = (r: number) => { setRate(r); player?.setRate(r) }
  const seekTo = useCallback((seg: Segment) => { player?.seek(seg.start); player?.play() }, [player])
  const toggleLoop = (seg: Segment) => {
    if (loopIdx === seg.idx) return setLoopIdx(null)
    setLoopIdx(seg.idx)
    seekTo(seg)
  }
  const savePhrase = (seg: Segment) => async (text: string) => {
    await api.savePhrase({
      text,
      context_sentence: seg.text,
      translation: text === seg.text ? seg.translation : '',
      source_kind: media?.kind ?? 'video',
      source_id: id,
      timestamp: seg.start,
    })
  }

  const backTo = media?.kind === 'podcast' ? '/library?tab=podcast' : '/videos'
  if (error) return <main className="p-8 text-rose-500">{error}　<Link to={backTo} className="underline">返回</Link></main>
  if (!media) return <main className="p-8 text-slate-400">載入中…</main>

  if (!canOpen) {
    return (
      <main className="mx-auto max-w-xl px-4 py-16 text-center">
        <h1 className="mb-6 text-xl font-semibold">{media.title}</h1>
        <p className={media.status === 'error' ? 'text-rose-500' : 'text-indigo-500'}>
          {statusText(media)}
        </p>
        {isProcessing(media) && (
          <div className="mx-auto mt-3 h-2 max-w-sm overflow-hidden rounded bg-slate-200 dark:bg-slate-700">
            <div className="h-full bg-indigo-500 transition-all" style={{ width: `${media.progress}%` }} />
          </div>
        )}
        {media.status === 'error' && (
          <>
            <p className="mt-2 text-sm text-slate-500">{media.error}</p>
            <button onClick={() => retry()} className="mt-4 rounded-lg bg-indigo-600 px-4 py-2 text-white">重試</button>
          </>
        )}
        <p className="mt-8"><Link to={backTo} className="text-slate-500 underline">{media.kind === 'podcast' ? '返回 Podcast 清單' : '返回影片清單'}</Link></p>
      </main>
    )
  }

  return (
    <div className="flex h-dvh flex-col gap-3 p-3 lg:flex-row">
      <div className="flex shrink-0 flex-col gap-2 lg:w-[55%]">
        <div className="flex items-center gap-2">
          <Link to={backTo} className="text-slate-500 hover:text-slate-800 dark:hover:text-slate-200">←</Link>
          <h1 className="line-clamp-1 flex-1 text-sm font-medium sm:text-base">{media.title}</h1>
        </div>
        {media.kind === 'podcast' ? (
          useFake ? (
            <div className="flex aspect-video items-center justify-center rounded-xl bg-slate-800 text-slate-400">模擬播放器（開發用）</div>
          ) : (
            <AudioPlayer src={mediaAudioUrl(id)} title={media.title} cover={media.thumbnail} duration={media.duration} startAt={startAt} onReady={setPlayer} />
          )
        ) : (
          /* The overlay swallows clicks so YouTube's own play/pause never fires; ours does instead. */
          <div className="relative">
            {useFake ? (
              <div className="flex aspect-video items-center justify-center rounded-xl bg-slate-800 text-slate-400">模擬播放器（開發用）</div>
            ) : (
              <YouTubePlayer videoId={media.external_id} startAt={startAt} onReady={setPlayer} />
            )}
            <div className="absolute inset-0 cursor-pointer rounded-xl" onClick={togglePlay} aria-hidden />
          </div>
        )}
        <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2 text-sm">
          <div className="flex items-center gap-1.5">
            <span className="text-slate-500">速度</span>
            {RATES.map((r) => (
              <button key={r} onClick={() => changeRate(r)} className={`rounded-md px-2 py-0.5 ${rate === r ? 'bg-indigo-600 text-white' : 'bg-slate-200 dark:bg-slate-700'}`}>{r}×</button>
            ))}
          </div>
          <PlaybackControls
            player={player}
            segments={segments}
            duration={media.duration}
            playing={clock.playing}
            onNavigate={() => setLoopIdx(null)}
          />
          <div className="flex items-center gap-3">
            <label className="flex items-center gap-1"><input type="checkbox" checked={showTranslation} onChange={(e) => setShowTranslation(e.target.checked)} />翻譯</label>
            <label className="flex items-center gap-1"><input type="checkbox" checked={autoScroll} onChange={(e) => setAutoScroll(e.target.checked)} />自動捲動</label>
          </div>
        </div>
      </div>
      <div className="flex min-h-0 flex-1 flex-col">
        <ProcessingBanner media={media} onRetry={retry} />
        <div className="min-h-0 flex-1">
        <TranscriptView
          segments={segments}
          clock={clock}
          showTranslation={showTranslation}
          translationPending={media.status !== 'ready'}
          autoScroll={autoScroll}
          loopIdx={loopIdx}
          onSeek={(seg) => {
            // Picking another sentence ends the loop; otherwise the loop would pull playback straight back.
            if (loopIdx !== null && seg.idx !== loopIdx) setLoopIdx(null)
            seekTo(seg)
          }}
          onWordClick={(text, seg) => text && setWord({ text, seg })}
          renderToolbar={(seg) => (
            <SentenceToolbar seg={seg} looping={loopIdx === seg.idx} onExplain={() => setExplain(seg)} onToggleLoop={() => toggleLoop(seg)} onShadow={() => openShadow(seg)} onSave={savePhrase(seg)} />
          )}
        />
        </div>
      </div>
      {word && (
        <WordPanel
          word={word.text}
          context={{ sentence: word.seg.text, translation: word.seg.translation, sourceId: id, sourceKind: media.kind, timestamp: word.seg.start }}
          onClose={() => setWord(null)}
        />
      )}
      {shadow && <ShadowingModal segment={shadow} onClose={() => setShadow(null)} />}
      {explain && <ExplainPanel sentence={explain.text} context={contextOf(segments, explain)} onClose={() => setExplain(null)} />}
    </div>
  )
}
