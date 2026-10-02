import { useState } from 'react'
import { api } from '../api/client'
import type { User } from '../api/types'

export const inputClass = 'w-full rounded-lg border border-slate-300 bg-white px-3 py-2 dark:border-slate-600 dark:bg-slate-900'

export function AuthCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <main className="mx-auto max-w-sm px-4 py-16">
      <h1 className="mb-1 text-center text-2xl font-bold">English Lab</h1>
      <p className="mb-6 text-center text-sm text-slate-500">{title}</p>
      <div className="rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-800">{children}</div>
    </main>
  )
}

export default function Login({ onLogin }: { onLogin: (user: User) => void }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      onLogin(await api.login(username, password))
    } catch (err) {
      setError((err as Error).message)
      setBusy(false)
    }
  }

  return (
    <AuthCard title="登入">
      <form onSubmit={submit} className="space-y-4">
        <label className="block">
          <span className="mb-1 block text-sm font-medium">帳號</span>
          <input className={inputClass} value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" autoCapitalize="none" autoFocus required />
        </label>
        <label className="block">
          <span className="mb-1 block text-sm font-medium">密碼</span>
          <input className={inputClass} type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
        </label>
        {error && <p role="alert" className="text-sm text-rose-500">{error}</p>}
        <button disabled={busy} className="w-full rounded-lg bg-indigo-600 px-4 py-2 font-medium text-white hover:bg-indigo-500 disabled:opacity-50">
          {busy ? '登入中…' : '登入'}
        </button>
        <p className="text-center text-xs text-slate-500">需要邀請碼才能註冊，請向管理員索取邀請連結。</p>
      </form>
    </AuthCard>
  )
}
