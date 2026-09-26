import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { Book } from '../api/types'
import { LEVEL_STYLES, formatWords, readingStatus } from '../lib/books'

export default function BookCard({ book, onChanged }: { book: Book; onChanged: () => void }) {
  const [coverFailed, setCoverFailed] = useState(false)
  const news = book.source === 'news'
  const path = news ? `/news/${book.id}` : `/books/${book.id}`
  return (
    <div className="flex overflow-hidden rounded-2xl border border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-800" data-book-card>
      <Link to={path} className="w-24 shrink-0" aria-label={`閱讀 ${book.title}`}>
        {book.cover && !coverFailed ? (
          <img src={book.cover} alt="" loading="lazy" onError={() => setCoverFailed(true)} className="h-full min-h-32 w-full object-cover" />
        ) : (
          <div className="flex h-full min-h-32 w-full items-center justify-center bg-gradient-to-br from-amber-300 to-orange-500 p-2 text-center text-xs font-semibold text-white">
            {book.title.slice(0, 40)}
          </div>
        )}
      </Link>
      <div className="min-w-0 flex-1 p-3">
        <Link to={path} className="line-clamp-2 font-medium hover:underline">{book.title}</Link>
        {news ? (
          <p className="truncate text-sm text-slate-500">{[book.site, book.published].filter(Boolean).join(' · ')}</p>
        ) : (
          book.author && <p className="truncate text-sm text-slate-500">{book.author}</p>
        )}
        <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
          {book.level && (
            <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${LEVEL_STYLES[book.level]}`} title="難度是估計值，依生字比例與句子長度計算" data-level>
              {book.level}
            </span>
          )}
          <span className="text-slate-400">{news ? formatWords(book.word_count) : `${formatWords(book.word_count)} · ${book.chapter_count} 章`}</span>
        </div>
        <p className="mt-1 text-sm text-slate-500" data-reading-status>{readingStatus(book)}</p>
        {book.progress_percent > 0 && (
          <div className="mt-1 h-1 overflow-hidden rounded bg-slate-200 dark:bg-slate-700">
            <div className="h-full bg-indigo-500" style={{ width: `${book.progress_percent}%` }} />
          </div>
        )}
        <button
          onClick={() => confirm(`刪除「${book.title}」？（含閱讀進度與已存的翻譯）`) && api.deleteBook(book.id).then(onChanged)}
          className="mt-2 text-sm text-slate-400 hover:text-rose-500"
        >
          刪除
        </button>
      </div>
    </div>
  )
}
