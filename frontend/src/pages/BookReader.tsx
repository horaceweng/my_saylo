import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { api, streamParagraphTranslation } from '../api/client'
import type { BookChapter, BookDetail, BookParagraph as ParagraphData } from '../api/types'
import BookParagraph, { type TranslationState } from '../components/BookParagraph'
import ExplainPanel from '../components/ExplainPanel'
import ReadAloudBar from '../components/ReadAloudBar'
import WordMarksBar from '../components/WordMarksBar'
import WordPanel from '../components/WordPanel'
import { useReadAloud } from '../hooks/useReadAloud'
import { useWordMarks } from '../hooks/useWordMarks'
import { LEVEL_STYLES, formatWords, sentenceAt } from '../lib/books'

/** The chapter that holds paragraph number `paragraph` (counted over the whole book). */
export function chapterOf(book: BookDetail, paragraph: number): number {
  const found = book.chapters.find((c) => paragraph >= c.first_paragraph && paragraph < c.first_paragraph + c.paragraph_count)
  return found ? found.idx : 0
}

export default function BookReader() {
  const id = Number(useParams().id)
  const [query] = useSearchParams()
  const [book, setBook] = useState<BookDetail | null>(null)
  const [chapter, setChapter] = useState<BookChapter | null>(null)
  const [error, setError] = useState('')
  const [tocOpen, setTocOpen] = useState(false)
  const [translations, setTranslations] = useState<Record<number, TranslationState>>({})
  const [word, setWord] = useState<{ text: string; sentence: string; paragraph: ParagraphData } | null>(null)
  const [explain, setExplain] = useState<{ sentence: string; context: string } | null>(null)
  const scroller = useRef<HTMLDivElement>(null)
  const aborts = useRef(new Map<number, AbortController>())
  const target = useRef<{ chapter: number; paragraph: number | null } | null>(null)
  const lastSaved = useRef('')
  const saveTimer = useRef<number>(0)
  const texts = useMemo(() => chapter?.paragraphs.map((p) => p.text) ?? [], [chapter])
  const marks = useWordMarks(texts)
  const continueReading = useRef(false)  // a chapter that was read to its end goes on with the next one
  const read = useReadAloud(texts, () => {
    if (book && chapter && chapter.idx < book.chapter_count - 1) {
      continueReading.current = true
      void openChapter(book.id, chapter.idx + 1)
    }
  })

  // Open the book where the learner left off (or where a saved phrase points to).
  useEffect(() => {
    let stale = false
    api.getBook(id).then((b) => {
      if (stale) return
      const asked = query.get('p')
      const paragraph = asked !== null ? Number(asked) : b.last_paragraph
      target.current = paragraph > 0 || asked !== null ? { chapter: chapterOf(b, paragraph), paragraph } : { chapter: b.last_chapter, paragraph: null }
      setBook(b)
      void openChapter(b.id, target.current.chapter)
    }).catch((e: Error) => !stale && setError(e.message))
    return () => { stale = true; aborts.current.forEach((a) => a.abort()); window.clearTimeout(saveTimer.current) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id])

  const openChapter = useCallback(async (bookId: number, idx: number) => {
    aborts.current.forEach((a) => a.abort())
    aborts.current.clear()
    setTocOpen(false)
    try {
      const data = await api.getChapter(bookId, idx)
      setChapter(data)
      setTranslations(Object.fromEntries(data.paragraphs.map((p) => [p.id, { status: p.translation ? 'done' : 'idle', text: p.translation, visible: false } as TranslationState])))
    } catch (e) {
      setError((e as Error).message)
    }
  }, [])

  // After a chapter appears: jump to the remembered paragraph, or to the top of the chapter.
  useEffect(() => {
    if (!chapter || !scroller.current) return
    const wanted = target.current?.chapter === chapter.idx ? target.current.paragraph : null
    const el = wanted !== null ? scroller.current.querySelector(`[data-paragraph="${wanted}"]`) : null
    if (el) (el as HTMLElement).scrollIntoView({ block: 'start' })
    else scroller.current.scrollTo({ top: 0 })
    target.current = null
  }, [chapter])

  // The next chapter starts being read as soon as it is on screen
  useEffect(() => {
    if (chapter && continueReading.current) {
      continueReading.current = false
      read.play(0)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chapter])

  // Keep the paragraph being read in view
  const readingParagraph = read.spoken?.paragraph
  useEffect(() => {
    if (readingParagraph === undefined) return
    scroller.current?.querySelector(`[data-paragraph="${chapter?.paragraphs[readingParagraph]?.idx}"]`)?.scrollIntoView({ block: 'center', behavior: 'smooth' })
  }, [readingParagraph, chapter])

  /** Reading starts at the first paragraph on screen. */
  const readFromView = () => {
    const box = scroller.current
    if (!box || !chapter) return
    const top = box.getBoundingClientRect().top
    const first = [...box.querySelectorAll<HTMLElement>('[data-paragraph]')].find((el) => el.getBoundingClientRect().bottom > top + 8)
    const at = first ? chapter.paragraphs.findIndex((p) => p.idx === Number(first.dataset.paragraph)) : 0
    read.play(Math.max(0, at))
  }

  // Remember the reading position: the first paragraph that is (at least partly) in view.
  const savePosition = useCallback(() => {
    const box = scroller.current
    if (!box || !book || !chapter) return
    const top = box.getBoundingClientRect().top
    const first = [...box.querySelectorAll<HTMLElement>('[data-paragraph]')].find((el) => el.getBoundingClientRect().bottom > top + 8)
    const paragraph = first ? Number(first.dataset.paragraph) : chapter.paragraphs[0]?.idx ?? 0
    const key = `${chapter.idx}:${paragraph}`
    if (key === lastSaved.current) return
    window.clearTimeout(saveTimer.current)
    saveTimer.current = window.setTimeout(() => {
      lastSaved.current = key
      api.saveBookProgress(book.id, chapter.idx, paragraph).catch(() => {})
    }, 1200)
  }, [book, chapter])

  const translate = (p: ParagraphData) => {
    const state = translations[p.id]
    const set = (patch: Partial<TranslationState>) => setTranslations((all) => ({ ...all, [p.id]: { ...all[p.id], ...patch } }))
    if (state.status === 'loading') return
    if (state.status === 'done') return set({ visible: !state.visible })
    const controller = new AbortController()
    aborts.current.set(p.id, controller)
    set({ status: 'loading', visible: true, text: '', error: undefined })
    streamParagraphTranslation(p.id, (text) => set({ text }), controller.signal)
      .then((text) => set({ status: 'done', text }))
      .catch((e: Error) => e.name !== 'AbortError' && set({ status: 'error', visible: true, error: e.message }))
  }

  const explainParagraph = (p: ParagraphData, index: number) => {
    // A selection inside the paragraph is explained on its own; otherwise the whole paragraph.
    const selection = window.getSelection()?.toString().trim() ?? ''
    const inside = selection && p.text.includes(selection.split(/\s+/)[0])
    const previous = chapter?.paragraphs[index - 1]?.text.slice(-300) ?? ''
    setExplain({ sentence: inside ? selection.slice(0, 1500) : p.text, context: previous })
  }

  if (error) return <main className="p-8 text-rose-500">{error}　<Link to="/library?tab=book" className="underline">返回</Link></main>
  if (!book) return <main className="p-8 text-slate-400">載入中…</main>

  const isNews = book.source === 'news'
  const backTo = isNews ? '/news' : '/library?tab=book'
  const multiChapter = book.chapter_count > 1

  const current = chapter ? book.chapters[chapter.idx] : null
  const toc = (
    <nav aria-label="目錄" className="flex-1 overflow-y-auto p-2">
      {book.chapters.map((c) => (
        <button
          key={c.idx}
          onClick={() => void openChapter(book.id, c.idx)}
          aria-current={chapter?.idx === c.idx}
          className={`block w-full rounded-lg px-3 py-2 text-left text-sm ${chapter?.idx === c.idx ? 'bg-indigo-50 font-medium text-indigo-700 dark:bg-indigo-500/15 dark:text-indigo-200' : 'hover:bg-slate-100 dark:hover:bg-slate-800'}`}
          data-chapter-link
        >
          <span className="line-clamp-2">{c.title}</span>
          <span className="text-xs text-slate-400">{formatWords(c.word_count)}</span>
        </button>
      ))}
    </nav>
  )
  const header = (
    <div className="border-b border-slate-200 p-3 dark:border-slate-700">
      <Link to={backTo} className="text-sm text-slate-500 hover:underline">{isNews ? '← 新聞' : '← 書庫'}</Link>
      <h1 className="mt-1 line-clamp-2 font-semibold">{book.title}</h1>
      <p className="flex flex-wrap items-center gap-2 text-sm text-slate-500">
        {book.author}
        {book.level && <span className={`rounded-full px-2 py-0.5 text-xs ${LEVEL_STYLES[book.level]}`}>{book.level}</span>}
      </p>
    </div>
  )

  return (
    <div className="flex h-dvh">
      {multiChapter && (
        <aside className="hidden w-72 shrink-0 flex-col border-r border-slate-200 dark:border-slate-700 lg:flex">
          {header}
          {toc}
        </aside>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-center gap-2 border-b border-slate-200 p-2 dark:border-slate-700 lg:hidden">
          <Link to={backTo} className="px-2 text-slate-500">←</Link>
          <span className="line-clamp-1 flex-1 text-sm font-medium">{book.title}</span>
          {multiChapter && <button onClick={() => setTocOpen(true)} className="rounded-lg border border-slate-300 px-3 py-1 text-sm dark:border-slate-600">目錄</button>}
        </div>
        <div ref={scroller} onScroll={savePosition} className="flex-1 overflow-y-auto" data-reader-scroll>
          {chapter && current && (
            <div className="mx-auto max-w-2xl px-5 py-8">
              {isNews ? (
                <header className="mb-6">
                  <h2 className="font-serif text-2xl font-bold leading-snug" data-chapter-title>{chapter.title}</h2>
                  <p className="mt-2 flex flex-wrap items-center gap-x-2 text-sm text-slate-500" data-article-meta>
                    <span>{[book.site, book.published].filter(Boolean).join(' · ')}</span>
                    {book.level && <span className={`rounded-full px-2 py-0.5 text-xs ${LEVEL_STYLES[book.level]}`}>{book.level}</span>}
                    {book.url && <a href={book.url} target="_blank" rel="noreferrer noopener" className="text-indigo-600 hover:underline">原文 ↗</a>}
                  </p>
                </header>
              ) : (
                <>
                  <p className="text-sm text-slate-400">第 {chapter.idx + 1} / {book.chapter_count} 章</p>
                  <h2 className="mb-6 mt-1 font-serif text-2xl font-bold" data-chapter-title>{chapter.title}</h2>
                </>
              )}
              {read.supported && read.state === 'idle' && (
                <button onClick={readFromView} className="mb-4 rounded-lg border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-100 dark:border-slate-600 dark:hover:bg-slate-800" data-action="read-aloud">
                  🔊 朗讀{isNews ? '這篇文章' : '這一章'}
                </button>
              )}
              {read.error && <p role="alert" className="mb-4 rounded-lg bg-rose-50 p-3 text-sm text-rose-600 dark:bg-rose-500/10">{read.error}</p>}
              <WordMarksBar enabled={marks.enabled} onEnabled={marks.setEnabled} myLevel={marks.myLevel} onMyLevel={marks.setMyLevel} />
              {chapter.paragraphs.map((p, index) => (
                <BookParagraph
                  key={p.id}
                  idx={p.idx}
                  text={p.text}
                  translation={translations[p.id] ?? { status: 'idle', text: '', visible: false }}
                  wordClass={marks.wordClass}
                  onWordClick={(w, offset) => { marks.markSeen(w); setWord({ text: w, sentence: sentenceAt(p.text, offset), paragraph: p }) }}
                  onTranslate={() => translate(p)}
                  onExplain={() => explainParagraph(p, index)}
                  onRead={read.supported ? () => read.play(index) : undefined}
                  spoken={read.spoken?.paragraph === index ? read.spoken : null}
                />
              ))}
              {multiChapter && <div className="mt-10 flex justify-between border-t border-slate-200 pt-4 dark:border-slate-700">
                <button disabled={chapter.idx === 0} onClick={() => void openChapter(book.id, chapter.idx - 1)} className="rounded-lg border border-slate-300 px-4 py-2 disabled:opacity-40 dark:border-slate-600">← 上一章</button>
                <button disabled={chapter.idx >= book.chapter_count - 1} onClick={() => void openChapter(book.id, chapter.idx + 1)} className="rounded-lg bg-indigo-600 px-4 py-2 text-white disabled:opacity-40" data-next-chapter>下一章 →</button>
              </div>}
            </div>
          )}
        </div>
        {read.state !== 'idle' && chapter && (
          <ReadAloudBar
            state={read.state}
            position={(read.spoken?.paragraph ?? 0) + 1}
            total={chapter.paragraphs.length}
            rate={read.rate}
            buffering={read.buffering}
            onRate={read.setRate}
            onPrev={read.prev}
            onNext={read.next}
            onPause={read.pause}
            onResume={read.resume}
            onStop={read.stop}
          />
        )}
      </div>

      {tocOpen && (
        <div className="fixed inset-0 z-30 flex lg:hidden" onMouseDown={(e) => e.target === e.currentTarget && setTocOpen(false)}>
          <div className="flex w-80 max-w-[85%] flex-col bg-white shadow-2xl dark:bg-slate-900">
            {header}
            {toc}
          </div>
          <div className="flex-1 bg-black/40" onClick={() => setTocOpen(false)} />
        </div>
      )}

      {word && (
        <WordPanel
          word={word.text}
          context={{ sentence: word.sentence, translation: '', sourceId: book.id, sourceKind: isNews ? 'news' : 'book', timestamp: word.paragraph.idx }}
          onClose={() => setWord(null)}
        />
      )}
      {explain && <ExplainPanel sentence={explain.sentence} context={explain.context} onClose={() => setExplain(null)} />}
    </div>
  )
}
