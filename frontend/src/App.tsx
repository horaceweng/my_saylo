import { Link, Route, Routes, useLocation } from 'react-router-dom'
import Home from './pages/Home'
import Phrases from './pages/Phrases'
import VideoList from './pages/VideoList'
import BookReader from './pages/BookReader'
import Library from './pages/Library'
import News from './pages/News'
import MediaPage from './pages/MediaPage'
import Review from './pages/Review'
import Settings from './pages/Settings'
import ErrorBoundary from './components/ErrorBoundary'
import SystemBanner from './components/SystemBanner'

function TopNav() {
  const { pathname } = useLocation()
  // The player page uses the whole viewport
  if (/^\/(videos|podcasts|books|news)\/\d+/.test(pathname)) return null
  return (
    <nav className="border-b border-slate-200 bg-white/70 backdrop-blur dark:border-slate-800 dark:bg-slate-900/70">
      <div className="mx-auto flex max-w-4xl items-center gap-5 px-4 py-3 text-sm">
        <Link to="/" className="font-bold">English Lab</Link>
        <Link to="/videos" className="text-slate-600 hover:text-indigo-600 dark:text-slate-300">影片</Link>
        <Link to="/library" className="text-slate-600 hover:text-indigo-600 dark:text-slate-300">書籍</Link>
        <Link to="/news" className="text-slate-600 hover:text-indigo-600 dark:text-slate-300">新聞</Link>
        <Link to="/phrases" className="ml-auto text-slate-600 hover:text-indigo-600 dark:text-slate-300">⭐ 片語庫</Link>
        <Link to="/settings" className="text-slate-600 hover:text-indigo-600 dark:text-slate-300">⚙️ 設定</Link>
      </div>
    </nav>
  )
}

function NotFound() {
  return (
    <main className="mx-auto max-w-md px-4 py-20 text-center">
      <p className="mb-2 text-4xl">🔍</p>
      <h1 className="mb-6 text-xl font-bold">找不到這一頁</h1>
      <Link to="/" className="rounded-lg bg-indigo-600 px-4 py-2 text-white hover:bg-indigo-500">回首頁</Link>
    </main>
  )
}

export default function App() {
  const { pathname } = useLocation()
  return (
    <>
      <TopNav />
      <SystemBanner />
      <ErrorBoundary key={pathname}>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/videos" element={<VideoList />} />
        <Route path="/videos/:id" element={<MediaPage />} />
        <Route path="/podcasts/:id" element={<MediaPage />} />
        <Route path="/phrases" element={<Phrases />} />
        <Route path="/phrases/review" element={<Review />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="/library" element={<Library />} />
        <Route path="/books/:id" element={<BookReader />} />
        <Route path="/news" element={<News />} />
        <Route path="/news/:id" element={<BookReader />} />
        <Route path="*" element={<NotFound />} />
      </Routes>
      </ErrorBoundary>
    </>
  )
}
