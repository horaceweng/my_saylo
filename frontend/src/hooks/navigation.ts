import type { Segment } from '../api/types'
import { findIndex } from './usePlaybackClock'

/** Start time of the previous / next sentence relative to time `t`, or null if there is none. */
export function sentenceTarget(segments: Segment[], t: number, dir: 'prev' | 'next'): number | null {
  if (segments.length === 0) return null
  const cur = findIndex(segments.map((s) => s.start), t)
  if (dir === 'next') return cur + 1 < segments.length ? segments[cur + 1].start : null
  if (cur < 0) return null
  // In the silence after a sentence has finished, "previous" means the one that just ended.
  if (t > segments[cur].end + 0.3) return segments[cur].start
  return segments[Math.max(cur - 1, 0)].start
}

export const clamp = (value: number, min: number, max: number) => Math.min(Math.max(value, min), max)
