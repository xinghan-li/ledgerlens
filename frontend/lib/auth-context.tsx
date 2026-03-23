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
    let refreshTimer: ReturnType<typeof setInterval> | null = null

    const unsubscribe = onAuthStateChanged(auth, async (user) => {
      if (refreshTimer) { clearInterval(refreshTimer); refreshTimer = null }
      if (!user) {
        setToken(null)
        return
      }
      try {
        const t = await user.getIdToken()
        setToken(t)
        // Proactive refresh every 50 minutes (token expires in 60 min)
        refreshTimer = setInterval(async () => {
          try {
            const fresh = await user.getIdToken(true)
            setToken(fresh)
          } catch { /* will retry next interval */ }
        }, 50 * 60 * 1000)
      } catch {
        setToken(null)
      }
    })
    return () => {
      unsubscribe()
      if (refreshTimer) clearInterval(refreshTimer)
    }
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
 * Security: Authorization header is only sent when the request goes to our trusted baseUrl.
 * Absolute URLs (path.startsWith('http')) are never sent the token to avoid token leakage.
 */
export async function authFetch(
  baseUrl: string,
  path: string,
  init: RequestInit & { headers?: Record<string, string> },
  ctx: { token: string | null; refreshToken: () => Promise<string | null> }
): Promise<Response> {
  const isAbsoluteUrl = path.startsWith('http')
  const url = isAbsoluteUrl ? path : `${baseUrl.replace(/\/$/, '')}${path.startsWith('/') ? path : `/${path}`}`

  const doFetch = (bearerToken: string | null) =>
    fetch(url, {
      ...init,
      headers: {
        ...init.headers,
        ...(bearerToken ? { Authorization: `Bearer ${bearerToken}` } : {}),
      },
    })

  const token = isAbsoluteUrl ? null : ctx.token
  let res = await doFetch(token)
  if (res.status === 401 && !isAbsoluteUrl) {
    const newToken = await ctx.refreshToken()
    if (newToken) res = await doFetch(newToken)
  }
  return res
}
