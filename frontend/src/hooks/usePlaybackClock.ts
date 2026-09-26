import { useEffect, useRef, useState } from 'react'
import type { PlayerAdapter } from '../components/players/types'
import type { Segment } from '../api/types'

export interface Clock {
  segIdx: number // segment being spoken (-1 before the first one)
  wordIdx: number // word inside that segment (-1 if none yet)
}

/** Last index whose `start` is <= t, or -1. Items must be sorted by start. */
export function findIndex(starts: number[], t: number): number {
  let lo = 0
  let hi = starts.length - 1
  let ans = -1
  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    if (starts[mid] <= t) {
      ans = mid
      lo = mid + 1
    } else hi = mid - 1
  }
  return ans
}

/** Which sentence and word are being spoken at time `t`. */
export function computeClock(segments: Segment[], t: number): Clock {
  let segIdx = findIndex(segments.map((s) => s.start), t)
  // Well past the end of the last sentence: nothing is being spoken.
  if (segIdx >= 0 && t > segments[segIdx].end + 1.5) segIdx = -1
  const wordIdx = segIdx >= 0 ? findIndex(segments[segIdx].words.map((w) => w.start), t) : -1
  return { segIdx, wordIdx }
}

/** Where to jump when looping sentence `loopIdx`, or null if playback is still inside it. */
export function loopSeekTarget(segments: Segment[], loopIdx: number | null, t: number): number | null {
  const seg = loopIdx === null ? undefined : segments[loopIdx]
  if (!seg) return null
  return t >= seg.end || t < seg.start - 0.5 ? seg.start : null
}

/**
 * One animation frame of work: where to jump (if the loop ended) and what the clock should show.
 * After a jump the clock is computed at the jump target, not at the old time; otherwise, when
 * sentences are back to back, the highlight would flash on the next sentence for one frame.
 */
export function resolveFrame(segments: Segment[], loopIdx: number | null, t: number): { jumpTo: number | null; clock: Clock } {
  const jumpTo = loopSeekTarget(segments, loopIdx, t)
  return { jumpTo, clock: computeClock(segments, jumpTo ?? t) }
}

/**
 * Follows the player with requestAnimationFrame and reports the current sentence and word.
 * State only changes when the indices change, so React re-renders a few times per second at most.
 * While `loopIdx` is set, playback jumps back to the start of that sentence when it ends.
 */
export function usePlaybackClock(player: PlayerAdapter | null, segments: Segment[], loopIdx: number | null): Clock & { playing: boolean } {
  const [clock, setClock] = useState<Clock>({ segIdx: -1, wordIdx: -1 })
  const [playing, setPlaying] = useState(false)
  const last = useRef(clock)
  const loopRef = useRef(loopIdx)
  loopRef.current = loopIdx

  useEffect(() => {
    if (!player) return
    let raf = 0
    let wasPlaying = false
    const tick = () => {
      const isPlaying = player.isPlaying()
      if (isPlaying !== wasPlaying) {
        wasPlaying = isPlaying
        setPlaying(isPlaying)
      }
      const t = player.getCurrentTime()
      const { jumpTo, clock: next } = resolveFrame(segments, loopRef.current, t)
      if (jumpTo !== null) player.seek(jumpTo)
      if (next.segIdx !== last.current.segIdx || next.wordIdx !== last.current.wordIdx) {
        last.current = next
        setClock(next)
      }
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [player, segments])

  return { ...clock, playing }
}
