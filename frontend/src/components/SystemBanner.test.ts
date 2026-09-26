import { describe, expect, it } from 'vitest'
import type { Health } from '../api/types'
import { problemsOf } from './SystemBanner'

const ok: Health = { ok: true, ollama: true, llm_model: 'qwen3.5:9b', llm_model_installed: true, dict: true, ffmpeg: true }

describe('problemsOf', () => {
  it('says nothing when everything works, or before the first answer', () => {
    expect(problemsOf(ok, false)).toEqual([])
    expect(problemsOf(null, false)).toEqual([])
  })
  it('tells how to start Ollama', () => {
    const [msg] = problemsOf({ ...ok, ollama: false, llm_model_installed: false }, false)
    expect(msg).toContain('ollama serve')
  })
  it('names the missing model with the command to get it', () => {
    const [msg] = problemsOf({ ...ok, llm_model_installed: false }, false)
    expect(msg).toContain('ollama pull qwen3.5:9b')
  })
  it('lists every problem, and only the backend problem when it is unreachable', () => {
    expect(problemsOf({ ...ok, dict: false, ffmpeg: false }, false)).toHaveLength(2)
    expect(problemsOf(ok, true)).toHaveLength(1)
  })

  it('does not ask for Ollama when the cloud does the work, but says when the cloud is not set up', () => {
    expect(problemsOf({ ...ok, ollama: true, llm_model_installed: true, llm_backend: 'cloud', cloud_configured: true }, false)).toEqual([])
    const [msg] = problemsOf({ ...ok, llm_backend: 'cloud', cloud_configured: false }, false)
    expect(msg).toContain('雲端')
    expect(problemsOf({ ...ok, stt_backend: 'cloud', stt_configured: false }, false)[0]).toContain('語音辨識')
  })
})
