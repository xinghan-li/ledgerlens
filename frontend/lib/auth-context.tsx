'use client'

import React, { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { onAuthStateChanged } from 'firebase/auth'
import { getFirebaseAuth, getAuthToken } from '@/lib/firebase'

type AuthContextValue = {
  token: string | null
  refreshToken: () => Promise<string | null>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [token, setToken] = useState<string | null>(null)

  useEffect(() => {
    const auth = getFirebaseAuth()
    const unsubscribe = onAuthStateChanged(auth, async (user) => {
      if (!user) {
        setToken(null)
        return
      }
      try {
        const t = await user.getIdToken()
        setToken(t)
      } catch {
        setToken(null)
      }
    })
    return () => unsubscribe()
  }, [])

  const refreshToken = useCallback(async (): Promise<string | null> => {
    const newToken = await getAuthToken(true)
    if (newToken) setToken(newToken)
    return newToken
  }, [])

  return (
    <AuthContext.Provider value={{ token, refreshToken }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) return null
  return ctx
}

/**
 * Fetch with Bearer token; on 401, refresh token and retry once. Returns the response.
 * Use this so that after idle expiry the user can succeed on next action (or we auto-retry).
 */
export async function authFetch(
  baseUrl: string,
  path: string,
  init: RequestInit & { headers?: Record<string, string> },
  ctx: { token: string | null; refreshToken: () => Promise<string | null> }
): Promise<Response> {
  const url = path.startsWith('http') ? path : `${baseUrl.replace(/\/$/, '')}${path.startsWith('/') ? path : `/${path}`}`
  const token = ctx.token
  if (!token) {
    return fetch(url, { ...init, headers: { ...init.headers } })
  }
  let res = await fetch(url, {
    ...init,
    headers: { ...init.headers, Authorization: `Bearer ${token}` },
  })
  if (res.status === 401) {
    const newToken = await ctx.refreshToken()
    if (newToken) {
      res = await fetch(url, {
        ...init,
        headers: { ...init.headers, Authorization: `Bearer ${newToken}` },
      })
    }
  }
  return res
}
