import { useEffect, useState } from 'react'
import { api, streamWordEnrichment } from '../api/client'
import type { PartialEnrichment, RootResult, WordPart, WordResult } from '../api/types'
import SidePanel, { Chip, Section } from './SidePanel'

const FORM_LABELS: Record<string, string> = {
  p: '過去式', d: '過去分詞', i: '現在分詞', '3': '第三人稱單數', s: '複數', r: '比較級', t: '最高級',
}
const LEVEL_STYLES = [
  'bg-slate-100 text-slate-600', 'bg-sky-100 text-sky-700', 'bg-emerald-100 text-emerald-700',
  'bg-amber-100 text-amber-700', 'bg-rose-100 text-rose-700',
]

interface Props {
  word: string
  context: { sentence: string; translation: string; sourceId: number; sourceKind: string; timestamp: number }
  onClose: () => void
}

export default function WordPanel({ word, context, onClose }: Props) {
  const [stack, setStack] = useState<string[]>([word])
  const current = stack[stack.length - 1]
  const [data, setData] = useState<WordResult | null>(null)
  const [error, setError] = useState('')
  // the AI part is written after the dictionary part is already on screen; it fills in as it is generated
  const [ai, setAi] = useState<PartialEnrichment | null>(null)
  const [aiState, setAiState] = useState<'idle' | 'writing' | 'done' | 'error'>('idle')
  const [aiError, setAiError] = useState('')
  const [root, setRoot] = useState<{ part: string; result: RootResult | null; error?: string } | null>(null)
  const [saved, setSaved] = useState(false)

  useEffect(() => { setStack([word]) }, [word])

  useEffect(() => {
    const abort = new AbortController()
    setData(null); setError(''); setRoot(null); setSaved(false)
    setAi(null); setAiState('idle'); setAiError('')
    api.getWord(current).then((d) => {
      if (abort.signal.aborted) return
      setData(d)
      if (!d.found) return
      if (d.ai) { setAi(d.ai); setAiState('done'); return }
      setAiState('writing')
      streamWordEnrichment(d.target ?? current, (partial) => !abort.signal.aborted && setAi(partial), abort.signal)
        .then((final) => { if (!abort.signal.aborted) { setAi(final); setAiState('done') } })
        .catch((e) => { if (!abort.signal.aborted) { setAiError(e.message); setAiState('error') } })
    }).catch((e) => !abort.signal.aborted && setError(e.message))
    return () => abort.abort()  // moving on to another word stops the AI writing for this one
  }, [current])

  const openRoot = (part: string, meaning: string) => {
    setRoot({ part, result: null })
    api.getRootWords(part, meaning)
      .then((result) => setRoot({ part, result }))
      .catch((e) => setRoot({ part, result: null, error: e.message }))
  }

  const save = async () => {
    await api.savePhrase({
      text: data?.entry?.word ?? current,
      translation: data?.entry?.translation.split('\n')[0] ?? '',
      context_sentence: context.sentence,
      source_kind: context.sourceKind,
      source_id: context.sourceId,
      timestamp: context.timestamp,
    })
    setSaved(true)
  }

  const entry = data?.entry

  return (
    <SidePanel title={entry?.word ?? current} onClose={onClose} onBack={stack.length > 1 ? () => setStack((s) => s.slice(0, -1)) : undefined}>
      {error && <p className="text-rose-500">{error}</p>}
      {!data && !error && <p className="text-slate-400">查詢中…</p>}
      {data && !data.found && <p className="text-slate-500">字典裡找不到「{current}」。</p>}
      {entry && (
        <>
          <div className="mb-4 flex flex-wrap items-center gap-2">
            {entry.phonetic && <span className="text-slate-500">/{entry.phonetic}/</span>}
            <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${LEVEL_STYLES[entry.level]}`}>{entry.level_label}</span>
            <button onClick={save} disabled={saved} className="ml-auto rounded-lg border border-slate-300 px-2.5 py-1 text-sm hover:bg-slate-100 disabled:opacity-60 dark:border-slate-600 dark:hover:bg-slate-800">
              {saved ? '已存入片語庫 ✓' : '＋ 存入片語庫'}
            </button>
          </div>
          {entry.is_inflection && <p className="mb-3 text-sm text-slate-500">「{current}」是 <b>{entry.word}</b> 的變化形</p>}
          <Section title="意義">
            <p className="whitespace-pre-line">{entry.translation}</p>
          </Section>
          {Object.keys(entry.forms).some((k) => FORM_LABELS[k]) && (
            <Section title="字形變化">
              <div className="flex flex-wrap gap-1.5">
                {Object.entries(entry.forms).filter(([k]) => FORM_LABELS[k]).map(([k, v]) => (
                  <Chip key={k}>{FORM_LABELS[k]}：{v}</Chip>
                ))}
              </div>
            </Section>
          )}
        </>
      )}

      {aiState === 'error' && (
        <p className="mb-4 rounded-lg bg-amber-50 p-3 text-sm text-amber-800 dark:bg-amber-500/10 dark:text-amber-200">
          AI 補充內容暫時無法取得：{aiError}
        </p>
      )}
      {ai && aiState !== 'error' && (
        <>
          {!!ai.english_definition && <Section title="英文解釋"><p>{ai.english_definition}</p></Section>}
          {!!ai.examples?.length && (
            <Section title="例句">
              <ul className="space-y-2">
                {ai.examples!.map((ex, i) => (
                  <li key={i}><p>{ex.en}</p><p className="text-sm text-slate-500">{ex.zh}</p></li>
                ))}
              </ul>
            </Section>
          )}
          {[ai.prefix, ai.root, ai.suffix].some((p) => p?.part) && (
            <Section title="字首・字根・字尾">
              <ul className="space-y-1">
                {([['字首', ai.prefix], ['字根', ai.root], ['字尾', ai.suffix]] as [string, Partial<WordPart> | undefined][]).flatMap(([label, p]) => (p?.part ? [{ label, part: p.part, meaning: p.meaning ?? '' }] : [])).map(({ label, part, meaning }) => (
                  <li key={label} className="flex items-center gap-2">
                    <span className="w-10 text-sm text-slate-400">{label}</span>
                    {label === '字根' ? (
                      <Chip onClick={() => aiState === 'done' && openRoot(part, meaning)}>{part} ▸ 同字根單字</Chip>
                    ) : (
                      <Chip>{part}</Chip>
                    )}
                    <span className="text-sm text-slate-500">{meaning}</span>
                  </li>
                ))}
              </ul>
              {root && (
                <div className="mt-3 rounded-lg border border-slate-200 p-3 dark:border-slate-700">
                  <p className="mb-2 text-sm font-medium">含有字根 <b>{root.part}</b> 的單字</p>
                  {!root.result && !root.error && <p className="text-sm text-slate-400">整理中…</p>}
                  {root.error && <p className="text-sm text-rose-500">{root.error}</p>}
                  {root.result?.words.length === 0 && <p className="text-sm text-slate-400">沒有找到可驗證的單字</p>}
                  <ul className="space-y-1">
                    {root.result?.words.map((w) => (
                      <li key={w.word}>
                        <button onClick={() => setStack((s) => [...s, w.word])} className="flex w-full gap-2 rounded px-1 py-0.5 text-left hover:bg-slate-100 dark:hover:bg-slate-800">
                          <b className="shrink-0">{w.word}</b>
                          <span className="truncate text-sm text-slate-500">{w.translation}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </Section>
          )}
          {!!ai.synonyms?.length && (
            <Section title="同義字"><div className="flex flex-wrap gap-1.5">{ai.synonyms!.map((s) => <Chip key={s} onClick={() => setStack((st) => [...st, s])}>{s}</Chip>)}</div></Section>
          )}
          {!!ai.antonyms?.length && (
            <Section title="反義字"><div className="flex flex-wrap gap-1.5">{ai.antonyms!.map((s) => <Chip key={s} onClick={() => setStack((st) => [...st, s])}>{s}</Chip>)}</div></Section>
          )}
        </>
      )}
      {aiState === 'writing' && <p className="animate-pulse text-slate-400">AI 整理中…</p>}
    </SidePanel>
  )
}
