/** Who is told when the server says "log in first" (a 401 on any call, streaming ones included). */
const listeners = new Set<() => void>()

export function onUnauthorized(callback: () => void): () => void {
  listeners.add(callback)
  return () => { listeners.delete(callback) }
}

export function notifyUnauthorized(): void {
  listeners.forEach((callback) => callback())
}

export const inviteLink = (origin: string, code: string) => `${origin}/register?code=${encodeURIComponent(code)}`

export function inviteCodeFrom(search: string): string {
  return new URLSearchParams(search).get('code')?.trim() ?? ''
}
