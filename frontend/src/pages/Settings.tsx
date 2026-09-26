import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { AppSettings, Health } from '../api/types'
import { MY_LEVEL_OPTIONS, loadMarksEnabled, loadMyLevel, saveMarksEnabled, saveMyLevel } from '../lib/wordMarks'
import { fetchSpeech, type SettingsPatch } from '../api/client'
import CloudSettings from '../components/CloudSettings'
import { SKIP_OPTIONS, SPEECH_RATES, loadNaturalVoice, loadSpeechEngine, saveNaturalVoice, saveSpeechEngine, loadShowTranslation, loadSkipSeconds, loadSpeechRate, loadVoiceName, saveShowTranslation, saveSkipSeconds, saveSpeechRate, saveVoiceName } from '../lib/prefs'
import { speechSupported, useTtsStatus, useVoices } from '../hooks/useReadAloud'
import { pickVoice } from '../lib/speech'

const box = 'rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-800'
const select = 'w-full rounded-lg border border-slate-300 bg-white px-3 py-2 dark:border-slate-600 dark:bg-slate-900'

function Row({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block py-3">
      <span className="mb-1 block font-medium">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-sm text-slate-500">{hint}</span>}
    </label>
  )
}

function Status({ ok, children }: { ok: boolean; children: React.ReactNode }) {
  return <li className={ok ? 'text-emerald-600 dark:text-emerald-400' : 'text-rose-500'}>{ok ? '✓' : '✗'} {children}</li>
}

export default function Settings() {
  const [settings, setSettings] = useState<AppSettings | null>(null)
  const [health, setHealth] = useState<Health | null>(null)
  const [loadError, setLoadError] = useState('')
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null)
  const [saving, setSaving] = useState(false)

  // Browser-side choices apply immediately
  const [skip, setSkip] = useState(loadSkipSeconds)
  const [showTranslation, setShowTranslation] = useState(loadShowTranslation)
  const [myLevel, setMyLevel] = useState(loadMyLevel)
  const [marks, setMarks] = useState(loadMarksEnabled)
  const [voiceName, setVoiceName] = useState(loadVoiceName)
  const [speechRate, setSpeechRate] = useState(loadSpeechRate)
  const [engine, setEngine] = useState(loadSpeechEngine)
  const [naturalVoice, setNaturalVoice] = useState(loadNaturalVoice)
  const [listening, setListening] = useState(false)
  const [listenError, setListenError] = useState('')
  const voices = useVoices()
  const tts = useTtsStatus()
  const shownVoice = pickVoice(voices, voiceName)?.name ?? ''
  const naturalOn = engine === 'auto' && tts?.available === true
  const shownNatural = naturalVoice || tts?.default_voice || ''

  const listen = async () => {
    window.speechSynthesis?.cancel()
    setListenError('')
    const text = 'Practice a little every day, and your English will grow.'
    if (naturalOn) {
      setListening(true)
      try {
        const audio = new Audio(await fetchSpeech(text, shownNatural))
        audio.playbackRate = speechRate
        audio.preservesPitch = true
        await audio.play()
      } catch (e) {
        setListenError((e as Error).message)
      } finally {
        setListening(false)
      }
      return
    }
    const sample = new SpeechSynthesisUtterance(text)
    const voice = pickVoice(voices, voiceName)
    if (voice) { sample.voice = voice; sample.lang = voice.lang }
    sample.rate = speechRate
    window.speechSynthesis.speak(sample)
  }

  useEffect(() => {
    api.getSettings().then(setSettings).catch((e) => setLoadError(e.message))
    api.health().then(setHealth).catch(() => undefined)
  }, [])

  const change = async (patch: SettingsPatch) => {
    setSaving(true); setMessage(null)
    try {
      setSettings(await api.updateSettings(patch))
      setMessage({ ok: true, text: '已儲存，下一次處理就會用新的設定' })
      api.health().then(setHealth).catch(() => undefined)
    } catch (e) {
      setMessage({ ok: false, text: (e as Error).message })
    } finally {
      setSaving(false)
    }
  }

  const whisper = settings?.whisper_models.find((w) => w.repo === settings.whisper_model)

  return (
    <main className="mx-auto max-w-2xl space-y-6 px-4 py-8">
      <h1 className="text-2xl font-bold">設定</h1>
      {loadError && <p className="rounded-lg bg-rose-50 p-3 text-rose-600 dark:bg-rose-500/10">{loadError}</p>}
      {message && (
        <p role="status" className={`rounded-lg p-3 ${message.ok ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300' : 'bg-rose-50 text-rose-600 dark:bg-rose-500/10'}`}>{message.text}</p>
      )}

      {settings && <CloudSettings settings={settings} onSaved={(saved) => { setSettings(saved); api.health().then(setHealth).catch(() => undefined) }} />}

      <section className={box}>
        <h2 className="mb-1 text-lg font-semibold">本機 AI 模型</h2>
        <p className="text-sm text-slate-500">只有選「在這台電腦上」時才會用到。</p>
        {!settings && !loadError && <p className="py-3 text-slate-400">載入中…</p>}
        {settings && (
          <>
            <Row
              label="翻譯與說明用的語言模型"
              hint={settings.ollama_ok ? '只列出 Ollama 裡已經下載的模型。模型越大越準，但也越慢。' : 'Ollama 沒有開，無法列出模型。請先執行 ollama serve。'}
            >
              <select
                className={select}
                disabled={saving}
                value={settings.llm_model}
                onChange={(e) => change({ llm_model: e.target.value })}
              >
                {!settings.llm_models.some((m) => m.name === settings.llm_model) && <option value={settings.llm_model}>{settings.llm_model}（未安裝）</option>}
                {settings.llm_models.map((m) => <option key={m.name} value={m.name}>{m.name}（{m.size_gb} GB）</option>)}
              </select>
            </Row>
            <Row
              label="語音辨識模型（Whisper）"
              hint={whisper && !whisper.downloaded ? '⚠️ 這個模型還沒下載，第一次處理影片時會先下載，需要一些時間。' : whisper?.note}
            >
              <select
                className={select}
                disabled={saving}
                value={settings.whisper_model}
                onChange={(e) => change({ whisper_model: e.target.value })}
              >
                {settings.whisper_models.map((w) => (
                  <option key={w.repo} value={w.repo}>{w.label}（{w.size}）{w.downloaded ? '' : ' — 尚未下載'}</option>
                ))}
              </select>
            </Row>
          </>
        )}
      </section>

      <section className={box}>
        <h2 className="mb-1 text-lg font-semibold">學習</h2>
        <Row label="前進／後退秒數" hint="影片與 Podcast 播放控制列上的按鈕">
          <select className={select} value={skip} onChange={(e) => { setSkip(Number(e.target.value)); saveSkipSeconds(Number(e.target.value)) }}>
            {SKIP_OPTIONS.map((n) => <option key={n} value={n}>{n} 秒</option>)}
          </select>
        </Row>
        <Row label="翻譯預設" hint="開啟影片或 Podcast 時，是否預設顯示每句的中文翻譯（播放頁上隨時可以切換）">
          <select className={select} value={showTranslation ? 'on' : 'off'} onChange={(e) => { const on = e.target.value === 'on'; setShowTranslation(on); saveShowTranslation(on) }}>
            <option value="on">顯示</option>
            <option value="off">隱藏</option>
          </select>
        </Row>
        <Row label="我的程度" hint="文章和書裡，高於這個程度的單字會畫底線">
          <select className={select} value={myLevel} onChange={(e) => { setMyLevel(Number(e.target.value)); saveMyLevel(Number(e.target.value)) }}>
            {MY_LEVEL_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </Row>
        <label className="flex items-center gap-2 py-3">
          <input type="checkbox" checked={marks} onChange={(e) => { setMarks(e.target.checked); saveMarksEnabled(e.target.checked) }} />
          <span className="font-medium">在閱讀時標出單字難度</span>
        </label>
      </section>

      {(speechSupported() || tts?.available) && (
        <section className={box}>
          <h2 className="mb-1 text-lg font-semibold">朗讀</h2>
          <Row
            label="聲音來源"
            hint={tts === null ? '檢查中…' : tts.available
              ? tts.model_downloaded ? '「自然語音」是在這台電腦上運算的神經網路語音，抑揚頓挫接近真人。' : '⚠️ 自然語音的模型還沒下載，第一次朗讀時會先下載約 330 MB，需要幾分鐘。'
              : `自然語音暫時無法使用：${tts.problems.join('；')}`}
          >
            <select className={select} value={engine} onChange={(e) => { const v = e.target.value === 'browser' ? 'browser' : 'auto'; setEngine(v); saveSpeechEngine(v) }}>
              <option value="auto">自然語音（推薦，需要後端）</option>
              <option value="browser">瀏覽器內建語音（較機械）</option>
            </select>
          </Row>
          {naturalOn ? (
            <Row label="聲音">
              <select className={select} value={shownNatural} onChange={(e) => { setNaturalVoice(e.target.value); saveNaturalVoice(e.target.value) }}>
                {tts!.voices.map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}
              </select>
            </Row>
          ) : (
            <Row label="聲音" hint="想要更自然的內建聲音：系統設定 → 輔助使用 → 朗讀內容 → 系統語音 → 管理語音，下載「進階」或「Premium」的英文語音，再重新整理這一頁。">
              {voices.length === 0 ? (
                <p className="text-sm text-slate-500">這個瀏覽器找不到英文語音。</p>
              ) : (
                <select className={select} value={shownVoice} onChange={(e) => { setVoiceName(e.target.value); saveVoiceName(e.target.value) }}>
                  {voices.map((v) => <option key={v.name} value={v.name}>{v.name}（{v.lang}）</option>)}
                </select>
              )}
            </Row>
          )}
          <Row label="速度">
            <select className={select} value={speechRate} onChange={(e) => { setSpeechRate(Number(e.target.value)); saveSpeechRate(Number(e.target.value)) }}>
              {SPEECH_RATES.map((r) => <option key={r} value={r}>{r}×</option>)}
            </select>
          </Row>
          <button onClick={listen} disabled={listening || (!naturalOn && voices.length === 0)} className="mb-2 rounded-lg border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-100 disabled:opacity-50 dark:border-slate-600 dark:hover:bg-slate-700">
            {listening ? '產生語音中…' : '🔊 試聽'}
          </button>
          {listenError && <p role="alert" className="text-sm text-rose-500">{listenError}</p>}
        </section>
      )}

      <section className={box}>
        <h2 className="mb-2 text-lg font-semibold">系統狀態</h2>
        {!health && <p className="text-slate-400">檢查中…</p>}
        {health && (
          <ul className="space-y-1 text-sm">
            <Status ok={health.ollama}>Ollama {health.ollama ? '運作中' : '沒有開（ollama serve）'}</Status>
            <Status ok={health.llm_model_installed}>語言模型 {health.llm_model} {health.llm_model_installed ? '已安裝' : '尚未安裝'}</Status>
            <Status ok={health.dict}>字典 {health.dict ? '已就緒' : '找不到'}</Status>
            <Status ok={health.ffmpeg}>ffmpeg {health.ffmpeg ? '已安裝' : '找不到'}</Status>
          </ul>
        )}
      </section>
    </main>
  )
}
