import { Link, Navigate, Route, Routes, useLocation } from 'react-router-dom'
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
import Login from './pages/Login'
import Register from './pages/Register'
import Users from './pages/Users'
import { AuthContext, useAuth, useSession } from './hooks/useAuth'

function TopNav() {
  const { pathname } = useLocation()
  const { user, logout } = useAuth()
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
        {user.is_admin && <Link to="/admin/users" className="text-slate-600 hover:text-indigo-600 dark:text-slate-300">👥 使用者</Link>}
        {user.is_admin && <Link to="/settings" className="text-slate-600 hover:text-indigo-600 dark:text-slate-300">⚙️ 設定</Link>}
        <span className="flex items-center gap-2 border-l border-slate-200 pl-4 text-slate-500 dark:border-slate-700">
          <span>{user.username}</span>
          <button onClick={logout} className="hover:text-indigo-600">登出</button>
        </span>
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

function AdminOnly({ children }: { children: React.ReactNode }) {
  return useAuth().user.is_admin ? <>{children}</> : <NotFound />
}

function AppPages() {
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
        <Route path="/settings" element={<AdminOnly><Settings /></AdminOnly>} />
        <Route path="/admin/users" element={<AdminOnly><Users /></AdminOnly>} />
        <Route path="/login" element={<Navigate to="/" replace />} />
        <Route path="/register" element={<Navigate to="/" replace />} />
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

/** Nothing of the app is shown until we know who is using it; with nobody logged in it is the login page (or the sign-up page for an invite link). */
export default function App() {
  const { pathname } = useLocation()
  const session = useSession()
  const { user, error } = session
  if (error) {
    return (
      <main className="mx-auto max-w-sm px-4 py-20 text-center">
        <p className="mb-4 text-rose-500">{error}</p>
        <button onClick={session.retry} className="rounded-lg bg-indigo-600 px-4 py-2 text-white hover:bg-indigo-500">再試一次</button>
      </main>
    )
  }
  if (user === undefined) return null
  if (user === null) return pathname === '/register' ? <Register onRegistered={session.setUser} /> : <Login onLogin={session.setUser} />
  return (
    <AuthContext.Provider value={{ user, logout: session.logout }}>
      <AppPages />
    </AuthContext.Provider>
  )
}
