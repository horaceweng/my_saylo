import { describe, expect, it } from 'vitest'
import { describeMicError, pickMimeType } from './useRecorder'

describe('pickMimeType', () => {
  it('takes the first supported format in order of preference', () => {
    expect(pickMimeType((t) => t.startsWith('audio/webm'))).toBe('audio/webm;codecs=opus')
    expect(pickMimeType((t) => t === 'audio/mp4')).toBe('audio/mp4') // Safari
  })
  it('lets the browser choose when nothing on the list is supported', () => {
    expect(pickMimeType(() => false)).toBeUndefined()
  })
})

describe('describeMicError', () => {
  it('explains the common failures in plain words', () => {
    expect(describeMicError({ name: 'NotAllowedError' })).toContain('權限')
    expect(describeMicError({ name: 'NotFoundError' })).toContain('找不到麥克風')
    expect(describeMicError({ name: 'NotReadableError' })).toContain('其他程式')
  })
  it('falls back to the original message', () => {
    expect(describeMicError(new Error('boom'))).toContain('boom')
  })
})
