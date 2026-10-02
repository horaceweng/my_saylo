import { useEffect, useState } from 'react'
import { streamExplain } from '../api/client'
import type { PartialExplanation } from '../api/types'
import { queueText } from '../lib/mediaStatus'
import SidePanel, { Section } from './SidePanel'

interface Props {
  sentence: string
  context: string
  onClose: () => void
}

export default function ExplainPanel({ sentence, context, onClose }: Props) {
  const [data, setData] = useState<PartialExplanation | null>(null)
  const [done, setDone] = useState(false)
  const [error, setError] = useState('')
  const [ahead, setAhead] = useState(0)

  useEffect(() => {
    const abort = new AbortController()
    setData(null); setDone(false); setError(''); setAhead(0)
    streamExplain(sentence, context, (partial) => { setAhead(0); setData(partial) }, abort.signal, setAhead)
      .then((final) => { setData(final); setDone(true) })
      .catch((e: Error) => e.name !== 'AbortError' && setError(e.message))
    return () => abort.abort()
  }, [sentence, context])

  const points = (data?.grammar_points ?? []).filter((g) => g.point)
  const phrases = (data?.phrases ?? []).filter((p) => p.phrase)
  const examples = (data?.similar_examples ?? []).filter((e) => e.en)

  return (
    <SidePanel title="AI 句子說明" onClose={onClose}>
      <p className="mb-4 rounded-lg bg-slate-100 p-3 text-lg dark:bg-slate-800">{sentence}</p>
      {error && <p className="text-rose-500">{error}</p>}
      {!data && !error && (ahead > 0
        ? <p className="text-amber-600 dark:text-amber-400" data-queued>{queueText(ahead)}…</p>
        : <p className="text-slate-400">AI 分析中…</p>)}
      {data && (
        <>
          {data.translation && <Section title="翻譯"><p>{data.translation}</p></Section>}
          {data.structure && <Section title="句型"><p className="font-medium">{data.structure}</p></Section>}
          {points.length > 0 && (
            <Section title="文法重點">
              <ul className="space-y-2">
                {points.map((g, i) => (
                  <li key={i}><b>{g.point}</b><p className="text-sm text-slate-600 dark:text-slate-300">{g.explanation}</p></li>
                ))}
              </ul>
            </Section>
          )}
          {phrases.length > 0 && (
            <Section title="片語・慣用語">
              <ul className="space-y-1">{phrases.map((p, i) => <li key={i}><b>{p.phrase}</b>　<span className="text-slate-500">{p.meaning}</span></li>)}</ul>
            </Section>
          )}
          {examples.length > 0 && (
            <Section title="相同句型的例句">
              <ul className="space-y-2">
                {examples.map((e, i) => (
                  <li key={i}><p>{e.en}</p><p className="text-sm text-slate-500">{e.zh}</p></li>
                ))}
              </ul>
            </Section>
          )}
          {!done && !error && <p className="animate-pulse text-sm text-indigo-500">生成中…</p>}
        </>
      )}
    </SidePanel>
  )
}
