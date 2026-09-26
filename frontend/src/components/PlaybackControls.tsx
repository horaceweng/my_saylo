import type { Segment } from '../api/types'
import { clamp, sentenceTarget } from '../hooks/navigation'
import { loadSkipSeconds } from '../lib/prefs'
import type { PlayerAdapter } from './players/types'

interface Props {
  player: PlayerAdapter | null
  segments: Segment[]
  duration: number
  playing: boolean
  /** Called before any jump so the page can end a sentence loop that would pull playback back. */
  onNavigate: () => void
}

const btn =
  'flex h-9 min-w-9 items-center justify-center rounded-lg px-2 text-sm transition-colors disabled:opacity-40 ' +
  'bg-slate-200 hover:bg-slate-300 dark:bg-slate-700 dark:hover:bg-slate-600'

export default function PlaybackControls({ player, segments, duration, playing, onNavigate }: Props) {
  const disabled = !player
  const SKIP_SECONDS = loadSkipSeconds()  // set on the settings page

  const skip = (delta: number) => {
    if (!player) return
    onNavigate()
    player.seek(clamp(player.getCurrentTime() + delta, 0, duration || Infinity))
  }
  const jump = (dir: 'prev' | 'next') => {
    if (!player) return
    const target = sentenceTarget(segments, player.getCurrentTime(), dir)
    if (target === null) return
    onNavigate()
    player.seek(target)
  }
  const toggle = () => (playing ? player?.pause() : player?.play())

  return (
    <div className="flex items-center gap-1.5" role="group" aria-label="播放控制">
      <button className={btn} disabled={disabled} onClick={() => jump('prev')} title="上一句" aria-label="上一句">⏮</button>
      <button className={btn} disabled={disabled} onClick={() => skip(-SKIP_SECONDS)} title={`後退 ${SKIP_SECONDS} 秒`} aria-label={`後退 ${SKIP_SECONDS} 秒`}>
        <span className="text-xs">−{SKIP_SECONDS}s</span>
      </button>
      <button
        className="flex h-10 w-12 items-center justify-center rounded-xl bg-indigo-600 text-lg text-white hover:bg-indigo-500 disabled:opacity-40"
        disabled={disabled}
        onClick={toggle}
        title={playing ? '暫停' : '播放'}
        aria-label={playing ? '暫停' : '播放'}
      >
        {playing ? '⏸' : '▶'}
      </button>
      <button className={btn} disabled={disabled} onClick={() => skip(SKIP_SECONDS)} title={`快進 ${SKIP_SECONDS} 秒`} aria-label={`快進 ${SKIP_SECONDS} 秒`}>
        <span className="text-xs">+{SKIP_SECONDS}s</span>
      </button>
      <button className={btn} disabled={disabled} onClick={() => jump('next')} title="下一句" aria-label="下一句">⏭</button>
    </div>
  )
}
