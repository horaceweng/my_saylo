import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import type { AdminUser, Invite } from '../api/types'
import { inviteLink } from '../lib/auth'
import { useAuth } from '../hooks/useAuth'

const box = 'rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-800'
const STATE_LABEL: Record<Invite['state'], string> = { open: '可使用', used: '已使用', expired: '已過期' }

function InviteRow({ invite }: { invite: Invite }) {
  const [copied, setCopied] = useState(false)
  const link = inviteLink(window.location.origin, invite.code)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(link)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      window.prompt('複製這個連結', link)
    }
  }
  return (
    <li className="flex flex-wrap items-center gap-2 py-2 text-sm">
      <input readOnly value={link} onFocus={(e) => e.target.select()} className="min-w-0 flex-1 rounded border border-slate-300 bg-slate-50 px-2 py-1 font-mono text-xs dark:border-slate-600 dark:bg-slate-900" />
      <span className={invite.state === 'open' ? 'text-emerald-600' : 'text-slate-500'}>
        {STATE_LABEL[invite.state]}{invite.used_by ? `（${invite.used_by}）` : ''}
      </span>
      {invite.state === 'open' && (
        <>
          <span className="text-xs text-slate-500">到期 {new Date(invite.expires_at).toLocaleDateString()}</span>
          <button onClick={copy} className="rounded border border-slate-300 px-2 py-1 hover:bg-slate-100 dark:border-slate-600 dark:hover:bg-slate-700">{copied ? '已複製' : '複製連結'}</button>
        </>
      )}
    </li>
  )
}

export default function Users() {
  const { user: me } = useAuth()
  const [users, setUsers] = useState<AdminUser[]>([])
  const [invites, setInvites] = useState<Invite[]>([])
  const [error, setError] = useState('')

  const load = useCallback(() => {
    Promise.all([api.adminUsers(), api.adminInvites()])
      .then(([u, i]) => { setUsers(u); setInvites(i) })
      .catch((e: Error) => setError(e.message))
  }, [])
  useEffect(load, [load])

  const run = (job: Promise<unknown>) => job.then(load).catch((e: Error) => setError(e.message))

  return (
    <main className="mx-auto max-w-3xl space-y-6 px-4 py-8">
      <h1 className="text-2xl font-bold">使用者</h1>
      {error && <p role="alert" className="text-sm text-rose-500">{error}</p>}

      <section className={box}>
        <div className="mb-2 flex items-center justify-between">
          <h2 className="font-semibold">邀請連結</h2>
          <button onClick={() => run(api.createInvite())} className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm text-white hover:bg-indigo-500">產生邀請連結</button>
        </div>
        <p className="mb-2 text-sm text-slate-500">每個連結只能註冊一個帳號，7 天內有效。</p>
        {invites.length === 0 ? <p className="py-2 text-sm text-slate-500">還沒有邀請連結</p> : (
          <ul className="divide-y divide-slate-200 dark:divide-slate-700">{invites.map((i) => <InviteRow key={i.code} invite={i} />)}</ul>
        )}
      </section>

      <section className={box}>
        <h2 className="mb-2 font-semibold">帳號</h2>
        <ul className="divide-y divide-slate-200 dark:divide-slate-700">
          {users.map((u) => (
            <li key={u.id} className="flex items-center gap-3 py-2 text-sm">
              <span className={u.disabled ? 'text-slate-400 line-through' : 'font-medium'}>{u.username}</span>
              {u.is_admin && <span className="rounded bg-indigo-100 px-1.5 text-xs text-indigo-700 dark:bg-indigo-500/20 dark:text-indigo-300">管理員</span>}
              {u.disabled && <span className="text-xs text-rose-500">已停用</span>}
              <span className="ml-auto text-xs text-slate-500">{new Date(u.created_at).toLocaleDateString()}</span>
              {u.id !== me.id && (
                <button onClick={() => run(api.setUserDisabled(u.id, !u.disabled))} className="rounded border border-slate-300 px-2 py-1 hover:bg-slate-100 dark:border-slate-600 dark:hover:bg-slate-700">
                  {u.disabled ? '啟用' : '停用'}
                </button>
              )}
            </li>
          ))}
        </ul>
      </section>
    </main>
  )
}
