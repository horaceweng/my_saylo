import type { PlayerAdapter } from './types'

/** Dev-only stand-in for a real player: time advances with the wall clock while "playing".
 * Enabled with `?fake=1` so the transcript UI can be exercised without streaming anything. */
export class FakePlayer implements PlayerAdapter {
  private time = 0
  private playing = false
  private rate = 1
  private stamp = performance.now()

  private advance() {
    const now = performance.now()
    if (this.playing) this.time += ((now - this.stamp) / 1000) * this.rate
    this.stamp = now
  }
  play() { this.advance(); this.playing = true }
  pause() { this.advance(); this.playing = false }
  seek(seconds: number) { this.advance(); this.time = seconds }
  getCurrentTime() { this.advance(); return this.time }
  setRate(rate: number) { this.advance(); this.rate = rate }
  isPlaying() { return this.playing }
}
