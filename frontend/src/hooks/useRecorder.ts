import { useCallback, useEffect, useRef, useState } from 'react'

export type RecorderState = 'idle' | 'recording' | 'recorded'

const MAX_SECONDS = 60
const PREFERRED_TYPES = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus']

/** The first recording format this browser supports, or undefined to let it choose. */
export function pickMimeType(isSupported: (type: string) => boolean): string | undefined {
  return PREFERRED_TYPES.find(isSupported)
}

export function describeMicError(error: unknown): string {
  const name = (error as { name?: string })?.name
  if (name === 'NotAllowedError' || name === 'SecurityError') return '麥克風權限被拒絕。請在瀏覽器網址列旁允許使用麥克風後再試一次。'
  if (name === 'NotFoundError' || name === 'OverconstrainedError') return '找不到麥克風，請確認裝置已連接。'
  if (name === 'NotReadableError') return '麥克風正被其他程式使用，請先關閉它。'
  return `無法使用麥克風：${(error as Error)?.message ?? '未知錯誤'}`
}

/** Records from the microphone with MediaRecorder; `blob` holds the finished recording. */
export function useRecorder() {
  const [state, setState] = useState<RecorderState>('idle')
  const [blob, setBlob] = useState<Blob | null>(null)
  const [seconds, setSeconds] = useState(0)
  const [error, setError] = useState('')
  const recorder = useRef<MediaRecorder | null>(null)
  const stream = useRef<MediaStream | null>(null)
  const timer = useRef<number>(0)

  const release = useCallback(() => {
    window.clearInterval(timer.current)
    stream.current?.getTracks().forEach((t) => t.stop())
    stream.current = null
  }, [])

  const stop = useCallback(() => {
    if (recorder.current?.state === 'recording') recorder.current.stop()
  }, [])

  /** Starts recording; resolves true once the microphone is live. `echoCancellation` removes what the
   * speakers play (still not perfect: headphones are the reliable way when shadowing at the same time). */
  const start = useCallback(async (options: { echoCancellation?: boolean } = {}): Promise<boolean> => {
    setError('')
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      setError('這個瀏覽器不支援錄音，請改用 Chrome、Edge 或 Safari。')
      return false
    }
    try {
      stream.current = await navigator.mediaDevices.getUserMedia({
        audio: options.echoCancellation ? { echoCancellation: true, noiseSuppression: true } : true,
      })
    } catch (e) {
      setError(describeMicError(e))
      return false
    }
    const chunks: BlobPart[] = []
    const mimeType = pickMimeType((t) => MediaRecorder.isTypeSupported(t))
    const rec = new MediaRecorder(stream.current, mimeType ? { mimeType } : undefined)
    recorder.current = rec
    rec.ondataavailable = (e) => e.data.size > 0 && chunks.push(e.data)
    rec.onstop = () => {
      release()
      setBlob(new Blob(chunks, { type: rec.mimeType || mimeType || 'audio/webm' }))
      setState('recorded')
    }
    rec.start()
    setBlob(null)
    setSeconds(0)
    setState('recording')
    const startedAt = Date.now()
    timer.current = window.setInterval(() => {
      const elapsed = Math.floor((Date.now() - startedAt) / 1000)
      setSeconds(elapsed)
      if (elapsed >= MAX_SECONDS) stop()
    }, 250)
    return true
  }, [release, stop])

  const reset = useCallback(() => {
    if (recorder.current?.state === 'recording') {
      recorder.current.onstop = null
      recorder.current.stop()
    }
    release()
    setBlob(null)
    setSeconds(0)
    setState('idle')
  }, [release])

  // Never leave the microphone on after the dialog is closed
  useEffect(() => () => {
    if (recorder.current?.state === 'recording') {
      recorder.current.onstop = null
      recorder.current.stop()
    }
    release()
  }, [release])

  return { state, blob, seconds, error, start, stop, reset }
}
