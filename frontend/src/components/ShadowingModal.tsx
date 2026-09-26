import { useEffect, useRef, useState } from 'react'
import { api, recordingAudioUrl, sentenceAudioUrl, streamFeedback } from '../api/client'
import type { PartialFeedback, Segment, ShadowRecording, TokenStatus } from '../api/types'
import { useRecorder } from '../hooks/useRecorder'
import { runSyncShadowing } from '../lib/syncShadowing'
import Waveform, { type WaveformHandle } from './Waveform'

const TOKEN_STYLE: Record<TokenStatus, string> = {
  ok: '',
  unclear: 'underline decoration-amber-500 decoration-wavy decoration-2 underline-offset-4',
  wrong: 'rounded bg-rose-100 px-0.5 text-rose-700 dark:bg-rose-500/20 dark:text-rose-300',
  missing: 'rounded border border-dashed border-rose-400 px-0.5 text-rose-500 line-through',
  extra: 'rounded bg-slate-200 px-0.5 text-sm italic text-slate-500 dark:bg-slate-700 dark:text-slate-300',
}

const LEGEND: [TokenStatus, string][] = [
  ['unclear', '不清楚'], ['wrong', '念成別的字'], ['missing', '漏掉'], ['extra', '多念'],
]

const mmss = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
const clock = (iso: string) => new Date(iso).toLocaleTimeString('zh-TW', { hour: '2-digit', minute: '2-digit' })

type Mode = 'listen' | 'sync'
const MODE_KEY = 'shadowing-mode'

function loadMode(): Mode {
  try {
    return localStorage.getItem(MODE_KEY) === 'sync' ? 'sync' : 'listen'
  } catch {
    return 'listen'
  }
}

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms))

export default function ShadowingModal({ segment, onClose }: { segment: Segment; onClose: () => void }) {
  const recorder = useRecorder()
  const [showSubtitle, setShowSubtitle] = useState(false) // start with the text hidden: listen first
  const [mode, setMode] = useState<Mode>(loadMode)
  const [countdown, setCountdown] = useState<number | null>(null)
  const [syncing, setSyncing] = useState(false)
  const cancelSync = useRef(false)
  const originalFinished = useRef<(() => void) | null>(null)
  const [history, setHistory] = useState<ShadowRecording[]>([])
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [comparing, setComparing] = useState(false)
  const [error, setError] = useState('')
  const [feedbackFor, setFeedbackFor] = useState<number | null>(null)
  const [partial, setPartial] = useState<PartialFeedback | null>(null)
  const [feedbackError, setFeedbackError] = useState('')
  const original = useRef<WaveformHandle>(null)
  const mine = useRef<WaveformHandle>(null)
  const abort = useRef<AbortController | null>(null)

  const selected = history.find((r) => r.id === selectedId) ?? null
  const tokens = selected?.tokens ?? []
  const feedback: PartialFeedback | null = selected?.feedback ?? (feedbackFor === selectedId ? partial : null)
  const mineSrc = selected ? recordingAudioUrl(selected.id) : recorder.blob

  useEffect(() => {
    let stale = false
    api.listRecordings(segment.id).then((rows) => !stale && setHistory(rows)).catch(() => {})
    return () => { stale = true }
  }, [segment.id])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('keydown', onKey)
      abort.current?.abort()
      cancelSync.current = true // never leave a countdown or a recording running behind a closed dialog
    }
  }, [onClose])

  const askFeedback = (id: number) => {
    abort.current?.abort()
    const controller = new AbortController()
    abort.current = controller
    setFeedbackFor(id); setPartial(null); setFeedbackError('')
    streamFeedback(id, setPartial, controller.signal)
      .then((final) => {
        setPartial(null)
        setHistory((rows) => rows.map((r) => (r.id === id ? { ...r, feedback: final } : r)))
      })
      .catch((e: Error) => e.name !== 'AbortError' && setFeedbackError(e.message))
  }

  const compare = async () => {
    if (!recorder.blob) return
    setComparing(true); setError('')
    try {
      const rec = await api.uploadRecording(segment.id, recorder.blob)
      setHistory((rows) => [rec, ...rows])
      setSelectedId(rec.id)
      recorder.reset()
      askFeedback(rec.id)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setComparing(false)
    }
  }

  const startRecording = () => {
    original.current?.pause(); mine.current?.pause()
    setSelectedId(null)
    void recorder.start()
  }

  /** Shadowing at the same time: countdown, record, play the original; stops itself shortly after it ends. */
  const startSync = async () => {
    original.current?.pause(); mine.current?.pause()
    setSelectedId(null)
    cancelSync.current = false
    setSyncing(true)
    await runSyncShadowing(
      {
        sleep,
        setCountdown,
        startRecording: () => recorder.start({ echoCancellation: true }),
        playOriginal: () => original.current?.playFromStart(),
        originalFinished: () => new Promise<void>((resolve) => { originalFinished.current = resolve }),
        stopRecording: recorder.stop,
        cancelled: () => cancelSync.current,
      },
      { maxWaitMs: (segment.end - segment.start + 4) * 1000 },
    )
    originalFinished.current = null
    setSyncing(false)
  }

  const stopSync = () => {
    cancelSync.current = true
    setCountdown(null) // hide it at once instead of waiting for the current countdown step to end
    original.current?.pause()
    originalFinished.current?.()
    recorder.stop()
  }

  const changeMode = (next: Mode) => {
    setMode(next)
    try { localStorage.setItem(MODE_KEY, next) } catch { /* the choice just is not remembered */ }
  }

  const select = (id: number) => {
    abort.current?.abort()
    setFeedbackFor(null); setPartial(null); setFeedbackError('')
    recorder.reset()
    setSelectedId(id)
  }

  const remove = async (id: number) => {
    await api.deleteRecording(id)
    setHistory((rows) => rows.filter((r) => r.id !== id))
    if (selectedId === id) setSelectedId(null)
  }

  const counts = tokens.reduce<Record<string, number>>((m, t) => ({ ...m, [t.status]: (m[t.status] ?? 0) + 1 }), {})

  return (
    <div className="fixed inset-0 z-40 flex items-end justify-center bg-black/50 sm:items-center" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div role="dialog" aria-label="Shadowing" className="flex max-h-[92dvh] w-full max-w-2xl flex-col rounded-t-2xl bg-white shadow-2xl dark:bg-slate-900 sm:rounded-2xl">
        <header className="flex items-center gap-2 border-b border-slate-200 px-4 py-3 dark:border-slate-700">
          <h2 className="flex-1 text-lg font-semibold">🎙 Shadowing</h2>
          <button onClick={onClose} aria-label="關閉" className="rounded px-2 py-1 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800">✕</button>
        </header>

        <div className="space-y-4 overflow-y-auto p-4">
          <section aria-label="字幕">
            <div className="mb-1 flex items-center justify-between">
              <h3 className="text-xs font-semibold tracking-wide text-slate-400">字幕</h3>
              <button
                onClick={() => setShowSubtitle((v) => !v)}
                aria-pressed={showSubtitle}
                className="rounded-lg border border-slate-300 px-2.5 py-1 text-sm hover:bg-slate-100 dark:border-slate-600 dark:hover:bg-slate-800"
              >
                {showSubtitle ? '🙈 隱藏字幕' : '👁 顯示字幕'}
              </button>
            </div>
            {showSubtitle ? (
              <div data-subtitle>
                <p className="text-xl leading-relaxed">{segment.text}</p>
                {segment.translation && <p className="text-slate-500">{segment.translation}</p>}
              </div>
            ) : (
              <p className="rounded-lg bg-slate-50 p-3 text-sm text-slate-400 dark:bg-slate-800/60" data-subtitle-hidden>
                字幕已隱藏：先用耳朵聽、用嘴巴跟。需要時再按「顯示字幕」。
              </p>
            )}
          </section>

          <Waveform ref={original} src={sentenceAudioUrl(segment.id)} title="原音" accent="#6366f1" placeholder="" onPlay={() => mine.current?.pause()} onFinish={() => originalFinished.current?.()} />
          <Waveform ref={mine} src={mineSrc} title="我的錄音" accent="#10b981" placeholder="按下「開始錄音」，跟著念這一句" onPlay={() => original.current?.pause()} />

          <div role="group" aria-label="練習方式" className="grid grid-cols-2 gap-1 rounded-xl bg-slate-100 p-1 dark:bg-slate-800">
            {([['listen', '🎧 先聽再念'], ['sync', '🗣 邊聽邊念']] as const).map(([value, label]) => (
              <button
                key={value}
                onClick={() => changeMode(value)}
                aria-pressed={mode === value}
                disabled={recorder.state === 'recording' || syncing}
                className={`rounded-lg px-3 py-1.5 text-sm font-medium transition-colors disabled:opacity-50 ${
                  mode === value ? 'bg-white shadow dark:bg-slate-600' : 'text-slate-500 hover:text-slate-800 dark:hover:text-slate-200'
                }`}
              >
                {label}
              </button>
            ))}
          </div>
          <p className="text-sm text-slate-500" data-mode-hint>
            {mode === 'listen'
              ? '先聽完原音，再自己錄一次。'
              : '按下開始後倒數 3 秒，原音開始播放，你同時跟著念；原音結束 1.5 秒後自動停止。'}
          </p>
          {mode === 'sync' && (
            <p className="rounded-lg bg-amber-50 p-2 text-sm text-amber-800 dark:bg-amber-500/10 dark:text-amber-200" data-headphones>
              🎧 請戴耳機。用喇叭的話，麥克風會把原音也錄進去，比對會把原音當成你念的，分數會不準。
            </p>
          )}

          <div className="flex flex-wrap items-center gap-2">
            {countdown !== null ? (
              <>
                <span className="rounded-xl bg-amber-500 px-4 py-2 text-lg font-bold text-white" data-countdown aria-live="assertive">準備… {countdown}</span>
                <button onClick={stopSync} className="rounded-xl border border-slate-300 px-4 py-2 dark:border-slate-600">✕ 取消</button>
              </>
            ) : recorder.state === 'recording' ? (
              <button onClick={mode === 'sync' ? stopSync : recorder.stop} className="flex animate-pulse items-center gap-2 rounded-xl bg-rose-600 px-4 py-2 font-medium text-white">
                ⏹ 停止（{mmss(recorder.seconds)}）
              </button>
            ) : (
              <button
                onClick={mode === 'sync' ? startSync : startRecording}
                disabled={syncing}
                className="rounded-xl bg-rose-600 px-4 py-2 font-medium text-white hover:bg-rose-500 disabled:opacity-50"
              >
                {recorder.state === 'recorded' || selected ? '🔁 重錄' : mode === 'sync' ? '▶ 開始同步跟讀' : '⏺ 開始錄音'}
              </button>
            )}
            <button
              onClick={compare}
              disabled={!recorder.blob || comparing || syncing}
              className="rounded-xl bg-indigo-600 px-4 py-2 font-medium text-white hover:bg-indigo-500 disabled:opacity-40"
            >
              {comparing ? '比對中…' : '✨ AI 比較'}
            </button>
          </div>
          {(recorder.error || error) && <p role="alert" className="rounded-lg bg-rose-50 p-3 text-sm text-rose-600 dark:bg-rose-500/10">{recorder.error || error}</p>}

          {selected && (
            <section aria-label="比較結果" className="space-y-3">
              <p className="text-xl leading-loose" data-shadow-sentence>
                {tokens.map((t, i) => (
                  <span key={i}>
                    <span className={TOKEN_STYLE[t.status]} data-status={t.status}>{t.status === 'extra' ? `+${t.text}` : t.text}</span>
                    {t.status === 'wrong' && t.heard && <span className="ml-1 text-xs text-rose-500">（聽成 {t.heard}）</span>}{' '}
                  </span>
                ))}
              </p>
              <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
                <span className="text-3xl font-bold" data-score>{selected.score}%</span>
                <span className="text-sm text-slate-500">完整度（念到的字 ÷ 句子的字）</span>
              </div>
              <div className="flex flex-wrap gap-x-3 gap-y-1 text-sm">
                {LEGEND.map(([status, label]) => (
                  <span key={status} className="flex items-center gap-1">
                    <span className={`${TOKEN_STYLE[status]} text-xs`}>{label}</span>
                    <span className="text-slate-500">{counts[status] ?? 0}</span>
                  </span>
                ))}
              </div>
              <p className="text-sm text-slate-500">聽到的內容：{selected.heard_text || '（沒有辨識到內容）'}</p>

              <div className="rounded-xl bg-slate-50 p-3 dark:bg-slate-800" data-feedback>
                <h3 className="mb-1 text-xs font-semibold tracking-wide text-slate-400">AI 評語</h3>
                {feedbackError && <p className="text-sm text-rose-500">{feedbackError}</p>}
                {!feedback && !feedbackError && feedbackFor === selected.id && <p className="animate-pulse text-sm text-indigo-500">AI 分析中…</p>}
                {!feedback && feedbackFor !== selected.id && (
                  <button onClick={() => askFeedback(selected.id)} className="text-sm text-indigo-600 hover:underline">產生 AI 評語</button>
                )}
                {feedback?.summary && <p>{feedback.summary}</p>}
                {feedback?.tips && feedback.tips.length > 0 && (
                  <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-600 dark:text-slate-300">
                    {feedback.tips.map((tip, i) => <li key={i}>{tip}</li>)}
                  </ul>
                )}
                {feedbackFor === selected.id && feedback && !selected.feedback && <p className="mt-2 animate-pulse text-xs text-indigo-500">生成中…</p>}
              </div>
              <p className="text-xs text-slate-400">
                比對依據語音辨識的結果，不是專業的發音評分。辨識會自動修正口音，所以結果可能偏寬鬆；「不清楚」表示辨識信心低，不代表一定念錯。
              </p>
            </section>
          )}

          {history.length > 0 && (
            <section aria-label="歷史紀錄">
              <h3 className="mb-1 text-xs font-semibold tracking-wide text-slate-400">這一句的練習紀錄</h3>
              <ul className="divide-y divide-slate-200 rounded-xl border border-slate-200 dark:divide-slate-700 dark:border-slate-700">
                {history.map((r) => (
                  <li key={r.id} className={`flex items-center gap-3 px-3 py-2 text-sm ${r.id === selectedId ? 'bg-indigo-50 dark:bg-indigo-500/10' : ''}`}>
                    <button onClick={() => select(r.id)} className="flex flex-1 items-center gap-3 text-left" aria-label={`查看 ${clock(r.created_at)} 的練習`}>
                      <span className="w-20 shrink-0 whitespace-nowrap text-slate-500">{clock(r.created_at)}</span>
                      <span className="w-12 shrink-0 font-semibold">{r.score}%</span>
                      <span className="truncate text-slate-500">{r.heard_text}</span>
                    </button>
                    <button onClick={() => remove(r.id)} aria-label="刪除這筆練習" className="text-slate-400 hover:text-rose-500">🗑</button>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>
      </div>
    </div>
  )
}
