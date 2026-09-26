import { useEffect, type ReactNode } from 'react'

interface Props {
  title: string
  onClose: () => void
  children: ReactNode
  onBack?: () => void
}

/** Bottom sheet on phones, right-hand drawer on wide screens. */
export default function SidePanel({ title, onClose, onBack, children }: Props) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <aside
      className="fixed inset-x-0 bottom-0 z-30 flex max-h-[75dvh] flex-col rounded-t-2xl border border-slate-200 bg-white shadow-2xl dark:border-slate-700 dark:bg-slate-900 sm:inset-y-0 sm:left-auto sm:right-0 sm:max-h-none sm:w-[420px] sm:rounded-none sm:rounded-l-2xl"
      role="dialog"
      aria-label={title}
    >
      <header className="flex items-center gap-2 border-b border-slate-200 px-4 py-3 dark:border-slate-700">
        {onBack && (
          <button onClick={onBack} className="rounded px-2 py-1 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800" aria-label="上一個">←</button>
        )}
        <h2 className="flex-1 truncate text-lg font-semibold">{title}</h2>
        <button onClick={onClose} className="rounded px-2 py-1 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800" aria-label="關閉">✕</button>
      </header>
      <div className="flex-1 overflow-y-auto p-4">{children}</div>
    </aside>
  )
}

export function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mb-5">
      <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-slate-400">{title}</h3>
      {children}
    </section>
  )
}

export function Chip({ children, onClick }: { children: ReactNode; onClick?: () => void }) {
  const cls = 'inline-block rounded-full bg-slate-100 px-2.5 py-0.5 text-sm dark:bg-slate-800'
  return onClick ? (
    <button onClick={onClick} className={`${cls} hover:bg-indigo-100 dark:hover:bg-indigo-500/20`}>{children}</button>
  ) : (
    <span className={cls}>{children}</span>
  )
}
