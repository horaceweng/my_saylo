import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { Health } from '../api/types'

/** What is wrong with the setup, in the learner's words (nothing when everything works). */
export function problemsOf(health: Health | null, unreachable: boolean): string[] {
  if (unreachable) return ['連不上後端：請確認已在 backend 資料夾啟動 fastapi（port 8000）']
  if (!health) return []
  const out: string[] = []
  if (health.llm_backend === 'cloud') {
    if (health.cloud_configured === false) out.push('已選擇雲端 AI，但 Base URL、模型或 API 金鑰還沒填好：請到「設定」完成')
  } else if (!health.ollama) out.push('Ollama 沒有開：翻譯、AI 說明與單字補充暫時無法使用。請在終端機執行 ollama serve，或到「設定」改用雲端 AI')
  else if (!health.llm_model_installed) out.push(`Ollama 裡沒有模型 ${health.llm_model}：請執行 ollama pull ${health.llm_model}，或到「設定」換一個`)
  if (health.stt_backend === 'cloud' && health.stt_configured === false) out.push('已選擇雲端語音辨識，但 Base URL 或模型還沒填好：請到「設定」完成')
  if (!health.dict) out.push('找不到字典檔：請執行 scripts/import_ecdict.py')
  if (!health.ffmpeg) out.push('找不到 ffmpeg：無法處理音訊，請先安裝（brew install ffmpeg）')
  return out
}

const POLL_MS = 15000

/** A small notice in the corner, only while something is wrong. It floats, so it never moves the page. */
export default function SystemBanner() {
  const [problems, setProblems] = useState<string[]>([])
  const [closed, setClosed] = useState('')

  useEffect(() => {
    let stop = false
    const check = () =>
      api.health()
        .then((h) => !stop && setProblems(problemsOf(h, false)))
        .catch(() => !stop && setProblems(problemsOf(null, true)))
    check()
    const timer = setInterval(check, POLL_MS)
    return () => { stop = true; clearInterval(timer) }
  }, [])

  const text = problems.join('\n')
  if (!text || closed === text) return null
  return (
    <div role="alert" className="fixed bottom-3 left-3 z-50 max-w-sm rounded-xl border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 shadow-lg dark:border-amber-500/40 dark:bg-amber-950 dark:text-amber-100">
      <div className="flex items-start gap-2">
        <ul className="flex-1 space-y-1">{problems.map((p) => <li key={p}>⚠️ {p}</li>)}</ul>
        <button onClick={() => setClosed(text)} aria-label="關閉提示" className="text-amber-700 hover:text-amber-900 dark:text-amber-300">✕</button>
      </div>
    </div>
  )
}
