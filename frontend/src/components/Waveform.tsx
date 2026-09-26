import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react'
import WaveSurfer from 'wavesurfer.js'

export interface WaveformHandle {
  pause(): void
  /** Rewind and play from the beginning. */
  playFromStart(): void
}

interface Props {
  /** URL or Blob of the audio to draw and play; null shows the placeholder. */
  src: string | Blob | null
  title: string
  accent: string
  placeholder: string
  /** Called when playback starts, so the page can pause other audio. */
  onPlay?: () => void
  /** Called when playback reaches the end. */
  onFinish?: () => void
}

const formatSeconds = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`

const Waveform = forwardRef<WaveformHandle, Props>(function Waveform({ src, title, accent, placeholder, onPlay, onFinish }, ref) {
  const container = useRef<HTMLDivElement>(null)
  const surfer = useRef<WaveSurfer | null>(null)
  const onPlayRef = useRef(onPlay)
  onPlayRef.current = onPlay
  const onFinishRef = useRef(onFinish)
  onFinishRef.current = onFinish
  const [playing, setPlaying] = useState(false)
  const [duration, setDuration] = useState(0)
  const [error, setError] = useState('')

  useImperativeHandle(ref, () => ({
    pause: () => surfer.current?.pause(),
    playFromStart: () => {
      surfer.current?.setTime(0)
      surfer.current?.play().catch(() => {}) // the browser may refuse; the guard timer then ends the take
    },
  }), [])

  useEffect(() => {
    setPlaying(false); setDuration(0); setError('')
    if (!src || !container.current) return
    const dark = window.matchMedia('(prefers-color-scheme: dark)').matches
    const url = typeof src === 'string' ? src : URL.createObjectURL(src)
    const ws = WaveSurfer.create({
      container: container.current,
      url,
      height: 56,
      waveColor: dark ? '#64748b' : '#94a3b8',
      progressColor: accent,
      cursorColor: accent,
      barWidth: 2,
      barGap: 2,
      barRadius: 2,
    })
    surfer.current = ws
    ws.on('ready', (d) => setDuration(d))
    ws.on('play', () => { setPlaying(true); onPlayRef.current?.() })
    ws.on('pause', () => setPlaying(false))
    ws.on('finish', () => { setPlaying(false); onFinishRef.current?.() })
    ws.on('error', () => setError('無法載入這段音訊'))
    return () => {
      ws.destroy()
      surfer.current = null
      if (typeof src !== 'string') URL.revokeObjectURL(url)
    }
  }, [src, accent])

  return (
    <div className="flex items-center gap-3 rounded-xl border border-slate-200 p-2 dark:border-slate-700">
      <button
        onClick={() => surfer.current?.playPause()}
        disabled={!src || !!error}
        aria-label={`${playing ? '暫停' : '播放'}${title}`}
        className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full text-white disabled:opacity-40"
        style={{ background: accent }}
      >
        {playing ? '⏸' : '▶'}
      </button>
      <div className="min-w-0 flex-1">
        <div className="mb-0.5 flex justify-between text-xs text-slate-500">
          <span>{title}</span>
          {duration > 0 && <span>{formatSeconds(duration)}</span>}
        </div>
        {src ? <div ref={container} /> : <p className="flex h-14 items-center text-sm text-slate-400">{placeholder}</p>}
        {error && <p className="text-sm text-rose-500">{error}</p>}
      </div>
    </div>
  )
})

export default Waveform
