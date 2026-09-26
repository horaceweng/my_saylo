import { useEffect, useRef } from 'react'
import type { PlayerAdapter } from './types'

/* Minimal typing for the parts of the IFrame API we use. */
interface YTPlayer {
  playVideo(): void
  pauseVideo(): void
  seekTo(seconds: number, allowSeekAhead: boolean): void
  getCurrentTime(): number
  setPlaybackRate(rate: number): void
  getPlayerState(): number
  destroy(): void
}
interface YTNamespace {
  Player: new (el: HTMLElement, opts: unknown) => YTPlayer
}
declare global {
  interface Window {
    YT?: YTNamespace
    onYouTubeIframeAPIReady?: () => void
  }
}

const PLAYING = 1
const BUFFERING = 3 // counts as playing so the play/pause button does not flicker on seeks
let apiPromise: Promise<YTNamespace> | null = null

function loadYouTubeApi(): Promise<YTNamespace> {
  if (window.YT?.Player) return Promise.resolve(window.YT)
  apiPromise ??= new Promise((resolve) => {
    window.onYouTubeIframeAPIReady = () => resolve(window.YT!)
    const tag = document.createElement('script')
    tag.src = 'https://www.youtube.com/iframe_api'
    document.head.appendChild(tag)
  })
  return apiPromise
}

interface Props {
  videoId: string
  startAt?: number
  onReady: (player: PlayerAdapter) => void
}

export default function YouTubePlayer({ videoId, startAt = 0, onReady }: Props) {
  const host = useRef<HTMLDivElement>(null)
  const onReadyRef = useRef(onReady)
  onReadyRef.current = onReady

  useEffect(() => {
    let player: YTPlayer | null = null
    let cancelled = false
    loadYouTubeApi().then((YT) => {
      if (cancelled || !host.current) return
      const mount = document.createElement('div')
      host.current.appendChild(mount)
      player = new YT.Player(mount, {
        videoId,
        width: '100%',
        height: '100%',
        // controls/keyboard off: playback is driven by our own control bar
        playerVars: { playsinline: 1, rel: 0, modestbranding: 1, controls: 0, disablekb: 1, fs: 0, iv_load_policy: 3, start: Math.floor(startAt) },
        events: {
          onError: (e: { data: number }) => console.error('[yt] player error', e.data),
          onReady: () => {
            const p = player!
            if (import.meta.env.DEV) (window as unknown as { __yt: YTPlayer }).__yt = p
            onReadyRef.current({
              play: () => p.playVideo(),
              pause: () => p.pauseVideo(),
              seek: (t) => p.seekTo(t, true),
              getCurrentTime: () => p.getCurrentTime(),
              setRate: (r) => p.setPlaybackRate(r),
              isPlaying: () => [PLAYING, BUFFERING].includes(p.getPlayerState()),
            })
          },
        },
      })
    })
    return () => {
      cancelled = true
      player?.destroy()
    }
    // startAt only matters for the initial load
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [videoId])

  return <div ref={host} className="aspect-video w-full overflow-hidden rounded-xl bg-black [&>iframe]:h-full [&>iframe]:w-full" />
}
