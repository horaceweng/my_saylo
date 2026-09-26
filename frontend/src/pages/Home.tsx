import { Link } from 'react-router-dom'

const sections = [
  { to: '/videos', title: '影片', desc: 'YouTube 字幕聽讀、單句循環、Shadowing', icon: '🎬' },
  { to: '/library', title: '書籍', desc: '書、Podcast，依能力分級', icon: '📚' },
  { to: '/news', title: '新聞', desc: '文章分段閱讀，單字依難度標色', icon: '📰' },
]

export default function Home() {
  return (
    <main className="mx-auto max-w-3xl px-4 py-12">
      <h1 className="mb-2 text-3xl font-bold">English Lab</h1>
      <p className="mb-8 text-slate-500">用真實的影片、書和新聞練習英文</p>
      <div className="grid gap-4 sm:grid-cols-3">
        {sections.map((s) => (
          <Link
            key={s.to}
            to={s.to}
            className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm transition hover:-translate-y-0.5 hover:shadow-md dark:border-slate-700 dark:bg-slate-800"
          >
            <div className="mb-3 text-4xl">{s.icon}</div>
            <div className="text-xl font-semibold">{s.title}</div>
            <div className="mt-1 text-sm text-slate-500 dark:text-slate-400">{s.desc}</div>
          </Link>
        ))}
      </div>
    </main>
  )
}
