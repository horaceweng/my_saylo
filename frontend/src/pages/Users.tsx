import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import type { AdminUser, AdminUsage, Invite } from '../api/types'
import { inviteLink } from '../lib/auth'
import { usageLine } from '../lib/usage'
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
  const [overview, setOverview] = useState<AdminUsage | null>(null)
  const [error, setError] = useState('')

  const load = useCallback(() => {
    Promise.all([api.adminUsers(), api.adminInvites(), api.adminUsage()])
      .then(([u, i, o]) => { setUsers(u); setInvites(i); setOverview(o) })
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

      {overview && (
        <section className={box} data-usage-overview>
          <h2 className="mb-2 font-semibold">雲端失敗改用本地的次數</h2>
          <p className="text-sm">
            語言模型：今天 {overview.fallbacks.llm.today} 次，近 7 天 {overview.fallbacks.llm.week} 次　·　
            語音辨識：今天 {overview.fallbacks.stt.today} 次，近 7 天 {overview.fallbacks.stt.week} 次
          </p>
          <p className="mt-1 text-xs text-slate-500">
            次數多代表雲端常常失敗或被限流，本地模型會被拉去跑（慢、吃記憶體）。每人每天上限：{overview.limits.media} 支影片／Podcast、{overview.limits.audio_minutes} 分鐘音訊、{overview.limits.ai} 次 AI 請求（管理員不受限，台北時間午夜重置）。
          </p>
        </section>
      )}

      <section className={box}>
        <h2 className="mb-2 font-semibold">帳號</h2>
        <ul className="divide-y divide-slate-200 dark:divide-slate-700">
          {users.map((u) => (
            <li key={u.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2 text-sm">
              <span className={u.disabled ? 'text-slate-400 line-through' : 'font-medium'}>{u.username}</span>
              {u.is_admin && <span className="rounded bg-indigo-100 px-1.5 text-xs text-indigo-700 dark:bg-indigo-500/20 dark:text-indigo-300">管理員</span>}
              {u.disabled && <span className="text-xs text-rose-500">已停用</span>}
              <span className="text-xs text-slate-500" title="今天的用量">今天：{usageLine(u.usage_today, overview?.limits)}</span>
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
