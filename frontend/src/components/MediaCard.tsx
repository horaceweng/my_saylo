import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { Media } from '../api/types'
import { LEVEL_STYLES } from '../lib/books'
import { formatDuration, isProcessing, mediaPath, statusText } from '../lib/mediaStatus'

/** One video or podcast in the library: cover, title, how far processing is, retry and delete. */
export default function MediaCard({ media, onChanged }: { media: Media; onChanged: () => void }) {
  const [coverFailed, setCoverFailed] = useState(false)
  const openable = media.playable
  const podcast = media.kind === 'podcast'
  const color = media.status === 'error' ? 'text-rose-500' : media.status === 'ready' ? 'text-emerald-600' : 'text-indigo-500'

  return (
    <div className={`overflow-hidden rounded-2xl border border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-800 ${podcast ? 'flex' : ''}`} data-media-card>
      <Link to={openable ? mediaPath(media) : '#'} className={`${openable ? '' : 'pointer-events-none'} ${podcast ? 'w-28 shrink-0' : 'block'}`} aria-label={`開啟 ${media.title}`}>
        {media.thumbnail && !coverFailed ? (
          <img src={media.thumbnail} alt="" loading="lazy" onError={() => setCoverFailed(true)} className={`w-full object-cover ${podcast ? 'h-full min-h-28' : 'aspect-video'}`} />
        ) : (
          <div className={`flex w-full items-center justify-center bg-gradient-to-br from-indigo-400 to-violet-500 text-4xl ${podcast ? 'h-full min-h-28' : 'aspect-video'}`}>🎧</div>
        )}
      </Link>
      <div className="min-w-0 flex-1 p-3">
        <p className="line-clamp-2 font-medium">{media.title}</p>
        <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
          <span className={color}>{statusText(media)}</span>
          {media.level && (
            <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${LEVEL_STYLES[media.level]}`} title="難度是估計值，依生字比例與句子長度計算" data-level>
              {media.level}
            </span>
          )}
          {media.duration > 0 && <span className="text-slate-400">{formatDuration(media.duration)}</span>}
          <span className="ml-auto flex gap-2">
            {media.status === 'error' && <button onClick={() => api.retryMedia(media.id).then(onChanged)} className="text-indigo-600 hover:underline">重試</button>}
            <button onClick={() => confirm(`刪除「${media.title}」？`) && api.deleteMedia(media.id).then(onChanged)} className="text-slate-400 hover:text-rose-500">刪除</button>
          </span>
        </div>
        {isProcessing(media) && (
          <div className="mt-2 h-1.5 overflow-hidden rounded bg-slate-200 dark:bg-slate-700">
            <div className="h-full bg-indigo-500 transition-all" style={{ width: `${media.progress}%` }} />
          </div>
        )}
        {media.status === 'error' && <p className="mt-1 text-xs text-rose-500">{media.error}</p>}
      </div>
    </div>
  )
}
