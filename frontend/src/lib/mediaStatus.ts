import type { Media } from '../api/types'

export const STATUS_LABELS: Record<Media['status'], string> = {
  pending: '排隊中', downloading: '下載音訊', transcribing: '語音轉文字', translating: '翻譯中', ready: '完成', error: '失敗',
}

export function isProcessing(m: Pick<Media, 'status'>) {
  return m.status !== 'ready' && m.status !== 'error'
}

/** Where the study page for this entry lives. `position` is a time in seconds for a video or podcast,
 * and a paragraph number for a book. */
export function mediaPath(m: { id: number; kind: string }, position?: number): string {
  if (m.kind === 'book' || m.kind === 'news') {
    const base = m.kind === 'news' ? `/news/${m.id}` : `/books/${m.id}`
    return position === undefined ? base : `${base}?p=${Math.round(position)}`
  }
  const base = m.kind === 'podcast' ? `/podcasts/${m.id}` : `/videos/${m.id}`
  return position === undefined ? base : `${base}?t=${position}`
}

/** "Waiting, N jobs ahead" for something in a line (a media job or an AI request); '' when nobody is ahead. */
export function queueText(ahead: number): string {
  return ahead > 0 ? `排隊中，前面還有 ${ahead} 個` : ''
}

/** The status line of a card: says when it can already be opened although processing goes on,
 * and how many jobs are ahead while it waits its turn. */
export function statusText(m: Media): string {
  if (m.status === 'pending' && m.queue_position > 0) return queueText(m.queue_position)
  if (m.playable && isProcessing(m)) return `可以開始看 · ${STATUS_LABELS[m.status]} ${m.progress}%`
  return `${STATUS_LABELS[m.status]}${isProcessing(m) ? ` ${m.progress}%` : ''}`
}

export function formatDuration(seconds: number): string {
  const s = Math.max(0, Math.round(seconds))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  return h > 0 ? `${h}:${String(m).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}` : `${m}:${String(s % 60).padStart(2, '0')}`
}
