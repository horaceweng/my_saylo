import { describe, expect, it } from 'vitest'
import { reasonLabel } from './cloud'

describe('reasonLabel', () => {
  it('names the HTTP status and the other kinds of failure', () => {
    expect(reasonLabel({ error_class: 'http', status_code: 403 })).toBe('HTTP 403')
    expect(reasonLabel({ error_class: 'timeout', status_code: null })).toBe('逾時')
    expect(reasonLabel({ error_class: 'connection', status_code: null })).toBe('連不上')
    expect(reasonLabel({ error_class: 'invalid_json', status_code: null })).toBe('回覆格式錯誤')
    expect(reasonLabel({ error_class: 'other', status_code: null })).toBe('其他')
  })
})
