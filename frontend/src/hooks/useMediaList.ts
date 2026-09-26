import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import type { Media } from '../api/types'
import { isProcessing } from '../lib/mediaStatus'

/** The entries of one kind, refreshed every few seconds while any of them is still being processed. */
export function useMediaList(kind: 'video' | 'podcast') {
  const [items, setItems] = useState<Media[] | null>(null)
  const [error, setError] = useState('')

  const refresh = useCallback(
    () => api.listMedia(kind).then((rows) => { setItems(rows); setError('') }).catch((e: Error) => setError(e.message)),
    [kind],
  )
  useEffect(() => { void refresh() }, [refresh])
  useEffect(() => {
    if (!items?.some(isProcessing)) return
    const timer = setInterval(refresh, 3000)
    return () => clearInterval(timer)
  }, [items, refresh])

  return { items, error, refresh }
}
