import type { MediaDetail } from '../api/types'

const mmss = (seconds: number) => {
  const s = Math.max(0, Math.floor(seconds))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

/** Shown above the transcript while the rest of a video is still being prepared. */
export default function ProcessingBanner({ media, onRetry }: { media: MediaDetail; onRetry: () => void }) {
  if (media.status === 'ready') return null
  if (media.status === 'error') {
    return (
      <div role="alert" className="mb-2 flex items-center gap-3 rounded-lg bg-rose-50 p-2 text-sm text-rose-600 dark:bg-rose-500/10">
        <span className="flex-1">處理中斷：{media.error || '未知錯誤'}（已完成的部分仍可使用）</span>
        <button onClick={onRetry} className="rounded-md bg-rose-600 px-2 py-1 text-white">繼續處理</button>
      </div>
    )
  }
  const transcript = media.transcribed ? '字幕完成' : `字幕 ${mmss(media.covered_until)} / ${mmss(media.duration)}`
  return (
    <div className="mb-2 rounded-lg bg-indigo-50 p-2 text-sm text-indigo-700 dark:bg-indigo-500/10 dark:text-indigo-200" data-processing-banner>
      <div className="flex flex-wrap items-center gap-x-3">
        <span className="font-medium">後面的內容還在處理</span>
        <span>{transcript}</span>
        <span>翻譯 {media.translated_count} / {media.sentence_count} 句</span>
      </div>
      {!media.transcribed && (
        <p className="mt-0.5 text-xs opacity-80">播到還沒處理的部分時沒有字幕，稍等一下就會出現。</p>
      )}
      <div className="mt-1 h-1 overflow-hidden rounded bg-indigo-200 dark:bg-indigo-500/30">
        <div className="h-full bg-indigo-500 transition-all" style={{ width: `${media.progress}%` }} />
      </div>
    </div>
  )
}
