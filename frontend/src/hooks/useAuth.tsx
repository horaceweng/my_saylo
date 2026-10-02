import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import type { User } from '../api/types'
import { onUnauthorized } from '../lib/auth'

interface Auth {
  user: User
  logout: () => Promise<void>
}

const AuthContext = createContext<Auth | null>(null)

/** The logged-in user; only used below <AuthGate>, which shows the login page instead when nobody is logged in. */
export function useAuth(): Auth {
  const auth = useContext(AuthContext)
  if (!auth) throw new Error('useAuth needs an <AuthGate>')
  return auth
}

export { AuthContext }

/** Finds out who is logged in. `undefined` while asking, `null` when nobody is, and a message when the server is out of reach. */
export function useSession() {
  const [user, setUser] = useState<User | null | undefined>(undefined)
  const [error, setError] = useState('')

  const check = useCallback(() => {
    setError('')
    api.me().then(setUser).catch((e: Error) => {
      if (e.message.includes('登入')) setUser(null)
      else setError(e.message)
    })
  }, [])

  useEffect(() => { check() }, [check])
  // Any call that comes back 401 later (the login ran out, or the account was disabled) ends up here
  useEffect(() => onUnauthorized(() => setUser(null)), [])

  const logout = useCallback(async () => {
    await api.logout().catch(() => undefined)
    setUser(null)
  }, [])

  return useMemo(() => ({ user, setUser, error, retry: check, logout }), [user, error, check, logout])
}
