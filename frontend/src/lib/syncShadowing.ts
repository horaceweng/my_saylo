/** Shadowing "at the same time": count down, start recording, play the original, and stop a moment
 * after the original ends so the learner can finish their last words. Kept free of React and of
 * real timers so the sequence can be tested with fakes. */

export interface SyncDeps {
  sleep(ms: number): Promise<void>
  setCountdown(n: number | null): void
  /** Resolves true when the microphone is recording, false if it could not be started. */
  startRecording(): Promise<boolean>
  playOriginal(): void
  /** Resolves when the original has finished playing. */
  originalFinished(): Promise<void>
  stopRecording(): void
  /** True once the learner pressed stop or closed the dialog. */
  cancelled(): boolean
}

export interface SyncOptions {
  countdownSeconds?: number
  stepMs?: number
  /** Extra recording time after the original ends. */
  tailMs?: number
  /** Give up waiting for the original after this long (it may never report that it finished). */
  maxWaitMs: number
}

export type SyncResult = 'done' | 'cancelled' | 'mic-failed'

export async function runSyncShadowing(d: SyncDeps, opts: SyncOptions): Promise<SyncResult> {
  const { countdownSeconds = 3, stepMs = 1000, tailMs = 1500, maxWaitMs } = opts
  try {
    for (let n = countdownSeconds; n >= 1; n--) {
      if (d.cancelled()) return 'cancelled'
      d.setCountdown(n)
      await d.sleep(stepMs)
    }
  } finally {
    d.setCountdown(null)
  }
  if (d.cancelled()) return 'cancelled'

  if (!(await d.startRecording())) return 'mic-failed'
  if (d.cancelled()) {
    d.stopRecording()
    return 'cancelled'
  }
  // Listen for the end before starting playback, so a very short clip cannot finish unnoticed.
  const finished = d.originalFinished()
  d.playOriginal()
  await Promise.race([finished, d.sleep(maxWaitMs)])
  if (d.cancelled()) return 'cancelled'
  await d.sleep(tailMs)
  if (d.cancelled()) return 'cancelled'
  d.stopRecording()
  return 'done'
}
