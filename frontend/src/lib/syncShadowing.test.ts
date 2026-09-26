import { describe, expect, it } from 'vitest'
import { runSyncShadowing, type SyncDeps } from './syncShadowing'

/** Fakes that record what happened in order; sleeping only advances a virtual clock. */
function setup(overrides: Partial<SyncDeps> = {}) {
  const log: string[] = []
  const sleeps: number[] = []
  let now = 0
  let cancelled = false
  let finishOriginal: () => void = () => {}
  const deps: SyncDeps = {
    sleep: async (ms) => { sleeps.push(ms); now += ms },
    setCountdown: (n) => { log.push(`countdown:${n}`) },
    startRecording: async () => { log.push(`record@${now}`); return true },
    playOriginal: () => { log.push(`play@${now}`) },
    originalFinished: () => new Promise<void>((resolve) => { finishOriginal = resolve }),
    stopRecording: () => { log.push(`stop@${now}`) },
    cancelled: () => cancelled,
    ...overrides,
  }
  return { deps, log, sleeps, cancel: () => { cancelled = true }, finish: () => finishOriginal(), clock: () => now }
}

describe('runSyncShadowing', () => {
  it('counts down, starts recording before the original, and stops after the tail', async () => {
    const t = setup()
    const run = runSyncShadowing(t.deps, { maxWaitMs: 60_000 })
    await Promise.resolve(); await Promise.resolve()
    t.finish()  // the original ends
    expect(await run).toBe('done')
    expect(t.log.map((l) => l.split('@')[0])).toEqual(['countdown:3', 'countdown:2', 'countdown:1', 'countdown:null', 'record', 'play', 'stop'])
    expect(t.sleeps).toEqual([1000, 1000, 1000, 60_000, 1500])  // countdown, the guard timer, then the tail after the original
  })

  it('hides the countdown afterwards', async () => {
    const shown: (number | null)[] = []
    const t = setup({ setCountdown: (n) => { shown.push(n) } })
    const run = runSyncShadowing(t.deps, { maxWaitMs: 1000 })
    expect(await run).toBe('done')
    expect(shown).toEqual([3, 2, 1, null])
  })

  it('does not play anything when the microphone cannot be started', async () => {
    const t = setup({ startRecording: async () => false })
    expect(await runSyncShadowing(t.deps, { maxWaitMs: 1000 })).toBe('mic-failed')
    expect(t.log.some((l) => l.startsWith('play') || l.startsWith('stop'))).toBe(false)
  })

  it('stops waiting if the original never reports that it finished', async () => {
    const t = setup({ originalFinished: () => new Promise<void>(() => {}) })
    expect(await runSyncShadowing(t.deps, { maxWaitMs: 8000, tailMs: 1000 })).toBe('done')
    expect(t.log.at(-1)).toBe('stop@12000')  // 3 s countdown + 8 s wait + 1 s tail
  })

  it('cancelling during the countdown never touches the microphone', async () => {
    const t = setup({ sleep: async () => { t.cancel() } })
    expect(await runSyncShadowing(t.deps, { maxWaitMs: 1000 })).toBe('cancelled')
    expect(t.log).toEqual(['countdown:3', 'countdown:null'])  // the countdown is hidden again
  })

  it('cancelling right as the microphone comes up stops it again', async () => {
    let cancelled = false
    const t = setup({
      cancelled: () => cancelled,
      startRecording: async () => { cancelled = true; return true },
    })
    expect(await runSyncShadowing(t.deps, { maxWaitMs: 1000 })).toBe('cancelled')
    expect(t.log.filter((l) => l.startsWith('stop')).length).toBe(1)
    expect(t.log.some((l) => l.startsWith('play'))).toBe(false)
  })

  it('cancelling while the original plays does not stop the recording a second time', async () => {
    const t = setup()
    const run = runSyncShadowing(t.deps, { maxWaitMs: 60_000 })
    await Promise.resolve(); await Promise.resolve()
    t.cancel(); t.finish()
    expect(await run).toBe('cancelled')
    expect(t.log.some((l) => l.startsWith('stop'))).toBe(false)  // the dialog's own stop handler does that
  })
})
