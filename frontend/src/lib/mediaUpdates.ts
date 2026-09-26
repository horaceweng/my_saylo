import type { MediaDetail, MediaUpdates, Segment } from '../api/types'

/** Fold what the server reported since the last look into the media the page already has.
 * The `segments` array is kept as it is (same reference) when nothing about the sentences changed,
 * so nothing that depends on it restarts for a mere progress update. */
export function mergeUpdates(prev: MediaDetail, updates: MediaUpdates): MediaDetail {
  const { new_segments, translations, ...meta } = updates
  const known = new Set(prev.segments.map((s) => s.idx))
  let changed = false
  const patched: Segment[] = prev.segments.map((s) => {
    const text = translations[String(s.idx)]
    if (s.translation || !text) return s
    changed = true
    return { ...s, translation: text }
  })
  const added = new_segments.filter((s) => !known.has(s.idx))
  if (added.length > 0) changed = true
  return { ...prev, ...meta, segments: changed ? [...patched, ...added].sort((a, b) => a.idx - b.idx) : prev.segments }
}

/** Index of the first sentence without a translation, or the sentence count if all have one. */
export function firstUntranslated(segments: Segment[]): number {
  const i = segments.findIndex((s) => !s.translation)
  return i === -1 ? segments.length : i
}

/** The polling interval: quick while nothing can be opened yet, relaxed afterwards. */
export function pollInterval(playable: boolean): number {
  return playable ? 3000 : 2000
}
