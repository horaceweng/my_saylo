import { useEffect, useRef, useState } from 'react'
import { formatDuration } from '../../lib/mediaStatus'
import type { PlayerAdapter } from './types'

/** The parts of an <audio> element the adapter uses (lets it be tested without a browser). */
export interface AudioLike {
  play(): Promise<void> | void
  pause(): void
  currentTime: number
  playbackRate: number
  paused: boolean
  ended: boolean
}

export function createAudioAdapter(el: AudioLike): PlayerAdapter {
  return {
    play: () => {
      // The browser may refuse (for example before any click on the page); nothing to do about it here.
      void Promise.resolve(el.play()).catch(() => {})
    },
    pause: () => el.pause(),
    seek: (seconds) => { el.currentTime = Math.max(0, seconds) },
    getCurrentTime: () => el.currentTime,
    setRate: (rate) => { el.playbackRate = rate },
    isPlaying: () => !el.paused && !el.ended,
  }
}

interface Props {
  src: string
  title: string
  cover?: string
  /** Length from the record, shown until the file itself reports it. */
  duration?: number
  startAt?: number
  onReady: (player: PlayerAdapter) => void
}

/** A podcast player: cover art and a seek bar. Play, pause and skipping come from the page's own controls. */
export default function AudioPlayer({ src, title, cover, duration = 0, startAt = 0, onReady }: Props) {
  const audio = useRef<HTMLAudioElement>(null)
  const onReadyRef = useRef(onReady)
  onReadyRef.current = onReady
  const [length, setLength] = useState(duration)
  const [time, setTime] = useState(0)
  const [coverFailed, setCoverFailed] = useState(false)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    const el = audio.current
    if (!el) return
    onReadyRef.current(createAudioAdapter(el))
    // startAt only matters for the first load
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [src])

  return (
    <div className="flex aspect-video w-full flex-col justify-end gap-2 overflow-hidden rounded-xl bg-gradient-to-br from-indigo-500 to-violet-600 p-4 text-white" data-audio-player>
      <div className="flex min-h-0 flex-1 items-center gap-4">
        {cover && !coverFailed ? (
          <img src={cover} alt="" onError={() => setCoverFailed(true)} className="h-full max-h-40 w-auto rounded-lg object-cover shadow-lg" />
        ) : (
          <div className="text-6xl">🎧</div>
        )}
        <p className="line-clamp-4 text-lg font-semibold drop-shadow">{title}</p>
      </div>
      {failed && <p role="alert" className="rounded bg-rose-600/80 px-2 py-1 text-sm">無法播放這個音檔，請確認後端仍在執行。</p>}
      <div className="flex items-center gap-2 text-xs tabular-nums">
        <span className="w-10 text-right">{formatDuration(time)}</span>
        <input
          type="range"
          min={0}
          max={length || 1}
          step={0.1}
          value={Math.min(time, length || 1)}
          onChange={(e) => { if (audio.current) audio.current.currentTime = Number(e.target.value) }}
          aria-label="播放位置"
          className="h-1.5 flex-1 accent-white"
        />
        <span className="w-10">{formatDuration(length)}</span>
      </div>
      <audio
        ref={audio}
        src={src}
        preload="auto"
        onLoadedMetadata={(e) => {
          const el = e.currentTarget
          if (Number.isFinite(el.duration)) setLength(el.duration)
          if (startAt > 0) el.currentTime = startAt
        }}
        onTimeUpdate={(e) => setTime(e.currentTarget.currentTime)}
        onError={() => setFailed(true)}
      />
    </div>
  )
}
