import { useState } from 'react'
import { api, type SettingsPatch } from '../api/client'
import type { AppSettings, CloudPreset } from '../api/types'

const box = 'rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-800'
const input = 'w-full rounded-lg border border-slate-300 bg-white px-3 py-2 dark:border-slate-600 dark:bg-slate-900'

interface Props {
  settings: AppSettings
  onSaved: (settings: AppSettings) => void
}

/** The preset a saved address belongs to ('custom' when it is none of them). */
export function presetFor(presets: CloudPreset[], baseUrl: string): string {
  return presets.find((p) => p.base_url && p.base_url === baseUrl)?.id ?? 'custom'
}

interface BlockProps {
  title: string
  local: string
  cloudLabel: string
  presets: CloudPreset[]
  cloud: boolean
  baseUrl: string
  model: string
  keyHint: string
  patch: (values: { cloud: boolean; baseUrl: string; model: string; key?: string }) => SettingsPatch
  target: 'llm' | 'stt'
  costNote: string
  onSaved: (settings: AppSettings) => void
}

function ServiceBlock(p: BlockProps) {
  const [cloud, setCloud] = useState(p.cloud)
  const [preset, setPreset] = useState(() => presetFor(p.presets, p.baseUrl))
  const [baseUrl, setBaseUrl] = useState(p.baseUrl)
  const [model, setModel] = useState(p.model)
  const [key, setKey] = useState('')
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null)
  const chosen = p.presets.find((x) => x.id === preset)

  const pick = (id: string) => {
    setPreset(id)
    const found = p.presets.find((x) => x.id === id)
    if (found && id !== 'custom') { setBaseUrl(found.base_url); setModel(found.model) }
  }

  const run = async (action: () => Promise<{ ok: boolean; text: string }>) => {
    setBusy(true); setResult(null)
    try {
      setResult(await action())
    } catch (e) {
      setResult({ ok: false, text: (e as Error).message })
    } finally {
      setBusy(false)
    }
  }

  const save = () => run(async () => {
    const saved = await api.updateSettings(p.patch({ cloud, baseUrl: baseUrl.trim(), model: model.trim(), key: key.trim() || undefined }))
    setKey('')
    p.onSaved(saved)
    return { ok: true, text: '已儲存' }
  })

  const forgetKey = () => run(async () => {
    p.onSaved(await api.updateSettings(p.patch({ cloud: false, baseUrl, model, key: '' })))
    setCloud(false)
    return { ok: true, text: '已清除金鑰，並改回本機' }
  })

  const test = () => run(async () => {
    const tested = await api.testConnection(p.target)
    return { ok: tested.ok, text: tested.message }
  })

  return (
    <div className="py-3">
      <h3 className="mb-2 font-medium">{p.title}</h3>
      <div className="mb-3 flex flex-col gap-1.5 text-sm">
        <label className="flex items-center gap-2"><input type="radio" checked={!cloud} onChange={() => setCloud(false)} />{p.local}</label>
        <label className="flex items-center gap-2"><input type="radio" checked={cloud} onChange={() => { setCloud(true); if (!baseUrl && p.presets[0]) pick(p.presets[0].id) }} />{p.cloudLabel}</label>
      </div>
      {cloud && (
        <div className="space-y-3 rounded-lg bg-slate-50 p-3 dark:bg-slate-900/50">
          <label className="block text-sm">服務
            <select className={`${input} mt-1`} value={preset} onChange={(e) => pick(e.target.value)}>
              {p.presets.map((x) => <option key={x.id} value={x.id}>{x.label}</option>)}
            </select>
            {chosen?.note && <span className="mt-1 block text-slate-500">{chosen.note}</span>}
          </label>
          <label className="block text-sm">Base URL
            <input className={`${input} mt-1`} value={baseUrl} onChange={(e) => { setBaseUrl(e.target.value); setPreset('custom') }} placeholder="https://…/v1" spellCheck={false} />
          </label>
          <label className="block text-sm">模型名稱
            <input className={`${input} mt-1`} value={model} onChange={(e) => setModel(e.target.value)} spellCheck={false} />
          </label>
          <label className="block text-sm">API 金鑰
            <input
              className={`${input} mt-1`}
              type="password"
              autoComplete="off"
              value={key}
              onChange={(e) => setKey(e.target.value)}
              placeholder={p.keyHint ? `已設定 ${p.keyHint}（留空表示不變）` : '貼上金鑰'}
            />
          </label>
          <p className="text-sm text-slate-500">{p.costNote}</p>
        </div>
      )}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button onClick={save} disabled={busy} className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-60">儲存</button>
        {p.cloud && <button onClick={test} disabled={busy} className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-100 disabled:opacity-60 dark:border-slate-600 dark:hover:bg-slate-700">測試連線</button>}
        {p.keyHint && <button onClick={forgetKey} disabled={busy} className="text-sm text-slate-400 hover:text-rose-500">清除金鑰並改回本機</button>}
        {busy && <span className="text-sm text-slate-400">處理中…</span>}
      </div>
      {result && <p role="status" className={`mt-2 text-sm ${result.ok ? 'text-emerald-600 dark:text-emerald-400' : 'text-rose-500'}`}>{result.text}</p>}
    </div>
  )
}

/** Choose where the AI work is done: on this computer, or by a cloud service paid by use. */
export default function CloudSettings({ settings, onSaved }: Props) {
  return (
    <section className={box}>
      <h2 className="mb-1 text-lg font-semibold">AI 服務：本機或雲端</h2>
      <p className="mb-2 text-sm text-slate-500">
        本機完全免費，但需要較多記憶體、處理較慢；雲端幾乎不吃電腦資源，也更快，按用量付費（估計一小時的影片翻譯加語音辨識約 USD 0.1，只是估算）。
        雲端模式會把字幕文字（語音辨識則是音訊）傳給該服務商；API 金鑰只存在這台電腦的資料庫，不會顯示在畫面上。
      </p>
      <ServiceBlock
        title="語言模型（翻譯、AI 說明、單字補充）"
        local="在這台電腦上用 Ollama（免費）"
        cloudLabel="使用雲端服務（OpenAI 相容的 API）"
        presets={settings.llm_presets}
        cloud={settings.llm_backend === 'cloud'}
        baseUrl={settings.cloud_base_url}
        model={settings.cloud_model}
        keyHint={settings.cloud_key}
        target="llm"
        costNote="Gemini 3.1 Flash-Lite 每百萬 token 輸入 $0.25、輸出 $1.50，是目前又便宜又夠用的選擇。價格會變動，請以服務商網站為準。"
        patch={({ cloud, baseUrl, model, key }) => ({ llm_backend: cloud ? 'cloud' : 'ollama', cloud_base_url: baseUrl, cloud_model: model, ...(key !== undefined ? { cloud_api_key: key } : {}) })}
        onSaved={onSaved}
      />
      <div className="border-t border-slate-200 dark:border-slate-700" />
      <ServiceBlock
        title="語音辨識（影片與 Podcast 轉字幕）"
        local="在這台電腦上用 Whisper（免費）"
        cloudLabel="使用雲端服務（OpenAI 相容的 API）"
        presets={settings.stt_presets}
        cloud={settings.stt_backend === 'cloud'}
        baseUrl={settings.stt_base_url}
        model={settings.stt_model}
        keyHint={settings.stt_key}
        target="stt"
        costNote="Groq 的 Whisper large-v3-turbo 每小時音訊 $0.04，一小時約 15 秒轉完。跟讀（shadowing）比較仍在本機處理。"
        patch={({ cloud, baseUrl, model, key }) => ({ stt_backend: cloud ? 'cloud' : 'local', stt_base_url: baseUrl, stt_model: model, ...(key !== undefined ? { stt_api_key: key } : {}) })}
        onSaved={onSaved}
      />
      <div className="border-t border-slate-200 dark:border-slate-700" />
      <FallbackToggle settings={settings} onSaved={onSaved} />
    </section>
  )
}

/** Whether a failing cloud service is covered by the local model. */
function FallbackToggle({ settings, onSaved }: Props) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const change = async (on: boolean) => {
    setBusy(true); setError('')
    try {
      onSaved(await api.updateSettings({ fallback_local: on }))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="py-3">
      <label className="flex items-start gap-2 text-sm">
        <input type="checkbox" className="mt-1" checked={settings.fallback_local} disabled={busy} onChange={(e) => change(e.target.checked)} />
        <span>
          <span className="font-medium">雲端失敗時改用本地模型</span>
          <span className="block text-slate-500">連不上、逾時、被限流（429）、伺服器錯誤或回覆不是有效 JSON 時，這一次改由這台電腦的 Ollama／Whisper 處理。本地一次只會載入一個模型（記憶體 16 GB），所以會比較慢，也可能要排隊。關閉後雲端失敗就直接顯示錯誤。</span>
        </span>
      </label>
      {error && <p role="alert" className="mt-1 text-sm text-rose-500">{error}</p>}
    </div>
  )
}
