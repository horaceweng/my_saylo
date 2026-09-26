import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import { extractWords, loadMarksEnabled, loadMyLevel, loadSeen, markClass, saveMarksEnabled, saveMyLevel, saveSeen, wordKey } from '../lib/wordMarks'

const CHUNK = 3000

/** Difficulty marks for the words of the texts on screen. Levels come from the dictionary (looked up once
 * per word); words the reader already opened or saved are remembered as "seen". */
export function useWordMarks(texts: string[]) {
  const [enabled, setEnabledState] = useState(loadMarksEnabled)
  const [myLevel, setMyLevelState] = useState(loadMyLevel)
  const [levels, setLevels] = useState<Record<string, number>>({})
  const [seen, setSeen] = useState<Set<string>>(loadSeen)
  const requested = useRef(new Set<string>())

  // Words saved in the phrase library count as seen too.
  useEffect(() => {
    let stale = false
    api.listPhrases('').then((rows) => {
      if (stale) return
      const saved = rows.map((p) => (p.text.trim().split(/\s+/).length === 1 ? wordKey(p.text) : '')).filter(Boolean)
      if (saved.length) setSeen((prev) => new Set([...prev, ...saved]))
    }).catch(() => {})
    return () => { stale = true }
  }, [])

  useEffect(() => {
    if (!enabled) return
    const fresh = extractWords(texts).filter((w) => !requested.current.has(w))
    if (fresh.length === 0) return
    fresh.forEach((w) => requested.current.add(w))
    void (async () => {
      try {
        for (let i = 0; i < fresh.length; i += CHUNK) {
          const { levels: got } = await api.wordLevels(fresh.slice(i, i + CHUNK))
          setLevels((prev) => ({ ...prev, ...got }))
        }
      } catch {
        fresh.forEach((w) => requested.current.delete(w))  // try again next time; the text is readable without marks
      }
    })()
  }, [texts, enabled])

  const wordClass = useCallback(
    (key: string, isName = false) => (enabled && key ? markClass(isName ? undefined : levels[key], myLevel, seen.has(key)) : ''),
    [enabled, levels, myLevel, seen],
  )

  const markSeen = useCallback((word: string) => {
    const key = wordKey(word)
    if (!key) return
    setSeen((prev) => {
      if (prev.has(key)) return prev
      const next = new Set(prev).add(key)
      saveSeen(next)
      return next
    })
  }, [])

  return {
    enabled,
    setEnabled: (on: boolean) => { setEnabledState(on); saveMarksEnabled(on) },
    myLevel,
    setMyLevel: (level: number) => { setMyLevelState(level); saveMyLevel(level) },
    wordClass,
    markSeen,
  }
}
