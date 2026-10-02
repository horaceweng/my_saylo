import { useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { api } from '../api/client'
import type { User } from '../api/types'
import { inviteCodeFrom } from '../lib/auth'
import { AuthCard, inputClass } from './Login'

export default function Register({ onRegistered }: { onRegistered: (user: User) => void }) {
  const { search } = useLocation()
  const [code, setCode] = useState(() => inviteCodeFrom(search))
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [again, setAgain] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (password !== again) return setError('兩次輸入的密碼不一樣')
    setBusy(true)
    setError('')
    try {
      onRegistered(await api.register(code, username, password))
    } catch (err) {
      setError((err as Error).message)
      setBusy(false)
    }
  }

  return (
    <AuthCard title="用邀請碼註冊">
      <form onSubmit={submit} className="space-y-4">
        <label className="block">
          <span className="mb-1 block text-sm font-medium">邀請碼</span>
          <input className={inputClass} value={code} onChange={(e) => setCode(e.target.value)} autoComplete="off" required />
        </label>
        <label className="block">
          <span className="mb-1 block text-sm font-medium">帳號</span>
          <input className={inputClass} value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" autoCapitalize="none" minLength={3} maxLength={32} required />
          <span className="mt-1 block text-xs text-slate-500">3–32 個英文字母、數字、底線、句點或連字號</span>
        </label>
        <label className="block">
          <span className="mb-1 block text-sm font-medium">密碼</span>
          <input className={inputClass} type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" minLength={8} required />
          <span className="mt-1 block text-xs text-slate-500">至少 8 個字元</span>
        </label>
        <label className="block">
          <span className="mb-1 block text-sm font-medium">再輸入一次密碼</span>
          <input className={inputClass} type="password" value={again} onChange={(e) => setAgain(e.target.value)} autoComplete="new-password" required />
        </label>
        {error && <p role="alert" className="text-sm text-rose-500">{error}</p>}
        <button disabled={busy} className="w-full rounded-lg bg-indigo-600 px-4 py-2 font-medium text-white hover:bg-indigo-500 disabled:opacity-50">
          {busy ? '註冊中…' : '註冊並登入'}
        </button>
        <p className="text-center text-sm"><Link to="/" className="text-indigo-600 hover:underline">已經有帳號？登入</Link></p>
      </form>
    </AuthCard>
  )
}
