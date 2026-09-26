/** Anything that can play media and report its position. YouTube and <audio> both implement it. */
export interface PlayerAdapter {
  play(): void
  pause(): void
  seek(seconds: number): void
  getCurrentTime(): number
  setRate(rate: number): void
  isPlaying(): boolean
}
