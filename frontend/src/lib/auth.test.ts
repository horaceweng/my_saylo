import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, streamExplain } from '../api/client'
import { inviteCodeFrom, inviteLink, onUnauthorized } from './auth'

afterEach(() => vi.unstubAllGlobals())

const reply = (status: number, body: unknown = {}) =>
  vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }))

describe('invite links', () => {
  it('builds the link and reads the code back from it', () => {
    const link = inviteLink('https://example.com', 'a b/c')
    expect(link).toBe('https://example.com/register?code=a%20b%2Fc')
    expect(inviteCodeFrom(new URL(link).search)).toBe('a b/c')
    expect(inviteCodeFrom('')).toBe('')
  })
})

describe('401 handling', () => {
  it('tells the app to show the login page when a normal call is refused', async () => {
    vi.stubGlobal('fetch', reply(401, { detail: '請先登入' }))
    const seen = vi.fn()
    const off = onUnauthorized(seen)
    await expect(api.listPhrases()).rejects.toThrow('請先登入')
    expect(seen).toHaveBeenCalledTimes(1)
    off()
  })

  it('also does so for the streaming calls', async () => {
    vi.stubGlobal('fetch', reply(401))
    const seen = vi.fn()
    const off = onUnauthorized(seen)
    await expect(streamExplain('Hi', '', () => undefined, new AbortController().signal)).rejects.toThrow('請先登入')
    expect(seen).toHaveBeenCalledTimes(1)
    off()
  })

  it('leaves a wrong password to the login form instead of reloading the login page', async () => {
    vi.stubGlobal('fetch', reply(401, { detail: '帳號或密碼不正確' }))
    const seen = vi.fn()
    const off = onUnauthorized(seen)
    await expect(api.login('a', 'b')).rejects.toThrow('帳號或密碼不正確')
    expect(seen).not.toHaveBeenCalled()
    off()
  })
})
