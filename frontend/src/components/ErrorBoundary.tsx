import { Component, type ErrorInfo, type ReactNode } from 'react'

/** A bug on one page should show a message and a way out, not a blank screen. */
export default class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null }

  static getDerivedStateFromError(error: Error) {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(error, info.componentStack)
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <main className="mx-auto max-w-md px-4 py-20 text-center">
        <p className="mb-2 text-4xl">😵</p>
        <h1 className="mb-2 text-xl font-bold">這一頁出了問題</h1>
        <p className="mb-6 text-sm text-slate-500">{this.state.error.message}</p>
        <a href="/" className="rounded-lg bg-indigo-600 px-4 py-2 text-white hover:bg-indigo-500">回首頁</a>
      </main>
    )
  }
}
