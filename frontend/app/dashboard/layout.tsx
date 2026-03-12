'use client'

import { useEffect, useState } from 'react'
import { useRouter, usePathname } from 'next/navigation'
import Link from 'next/link'
import { getFirebaseAuth } from '@/lib/firebase'
import { onAuthStateChanged, signOut } from 'firebase/auth'
import { useApiUrl } from '@/lib/api-url-context'
import { AuthProvider } from '@/lib/auth-context'
import { DashboardActionsProvider, useDashboardActions } from './dashboard-actions-context'

type UserInfo = {
  user_id: string
  email: string
  /** User tier: 0=free, 2=premium, 7=admin, 9=super_admin */
  user_class: number
  registration_no?: number
  registration_no_display?: string
  username?: string | null
} | null

function HeaderActionButtons() {
  const pathname = usePathname()
  const { actions, bannerInView } = useDashboardActions()
  const [justMounted, setJustMounted] = useState(true)
  useEffect(() => {
    if (!bannerInView) {
      setJustMounted(true)
      const t = requestAnimationFrame(() => {
        requestAnimationFrame(() => setJustMounted(false))
      })
      return () => cancelAnimationFrame(t)
    }
  }, [bannerInView])
  if (pathname !== '/dashboard' || !actions || bannerInView) return null
  const baseClass = 'inline-flex items-center justify-center w-9 h-9 rounded-lg min-h-[44px] min-w-[44px] sm:min-h-0 sm:min-w-0 sm:w-9 sm:h-9 shrink-0 transition-opacity hover:opacity-90'
  return (
    <span
      className={`flex items-center gap-1.5 transition-all duration-300 ease-out ${
        justMounted ? 'translate-x-2 opacity-0' : 'translate-x-0 opacity-100'
      }`}
    >
      <button type="button" onClick={() => actions.onReceiptHistory()} className={`${baseClass} border-2 border-theme-mid/40 bg-white text-theme-dark hover:bg-theme-light-gray/50`} aria-label="Receipt History"><span aria-hidden>🔍</span></button>
      <button type="button" onClick={() => actions.onUpload()} className={baseClass} style={{ backgroundColor: '#CC785C', color: '#FAFAF7' }} aria-label="Upload Receipt"><span aria-hidden>🧾</span></button>
      <button type="button" onClick={() => actions.onCamera()} className={baseClass} style={{ backgroundColor: '#191919', color: '#FAFAF7' }} aria-label="Camera"><span aria-hidden>📷</span></button>
    </span>
  )
}

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode
}) {
  const router = useRouter()
  const pathname = usePathname()
  const apiBaseUrl = useApiUrl()
  const [userInfo, setUserInfo] = useState<UserInfo>(null)
  const [loading, setLoading] = useState(true)
  const [navOpen, setNavOpen] = useState(false)
  const [mounted, setMounted] = useState(false)
  const [usernameModalOpen, setUsernameModalOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [unclassifiedCount, setUnclassifiedCount] = useState<number | null>(null)
  useEffect(() => {
    setMounted(true)
  }, [])

  useEffect(() => {
    const auth = getFirebaseAuth()
    const unsubscribe = onAuthStateChanged(auth, async (user) => {
      if (!user) {
        setUserInfo(null)
        setLoading(false)
        router.push('/login')
        return
      }
      try {
        const token = await user.getIdToken()
        const res = await fetch(`${apiBaseUrl}/api/auth/me`, {
          headers: { Authorization: `Bearer ${token}` },
        })
        if (res.ok) {
          const data = await res.json()
          const userClass = Number(data.user_class)
          setUserInfo({
            user_id: data.user_id,
            email: data.email,
            user_class: Number.isNaN(userClass) ? 0 : userClass,
            registration_no: data.registration_no,
            registration_no_display: data.registration_no_display,
            username: data.username,
          })
        } else {
          setUserInfo(null)
        }
      } catch {
        setUserInfo(null)
      } finally {
        setLoading(false)
      }
    })
    return () => unsubscribe()
  }, [router, apiBaseUrl])

  useEffect(() => {
    if (!userInfo || !pathname.startsWith('/dashboard')) return
    const auth = getFirebaseAuth()
    auth.currentUser?.getIdToken().then((token) => {
      fetch(`${apiBaseUrl}/api/analytics/summary`, { cache: 'no-store', headers: { Authorization: `Bearer ${token}` } })
        .then((r) => r.ok ? r.json() : null)
        .then((data) => { if (data?.unclassified_count != null) setUnclassifiedCount(data.unclassified_count) })
        .catch(() => {})
    })
  }, [userInfo, apiBaseUrl, pathname])

  const handleLogout = async () => {
    const auth = getFirebaseAuth()
    await signOut(auth)
    router.push('/')
  }

  const refetchUser = async () => {
    const auth = getFirebaseAuth()
    const user = auth.currentUser
    if (!user) return
    try {
      const token = await user.getIdToken()
      const res = await fetch(`${apiBaseUrl}/api/auth/me`, { headers: { Authorization: `Bearer ${token}` } })
      if (res.ok) {
        const data = await res.json()
        const userClass = Number(data.user_class)
        setUserInfo({
          user_id: data.user_id,
          email: data.email,
          user_class: Number.isNaN(userClass) ? 0 : userClass,
          registration_no: data.registration_no,
          registration_no_display: data.registration_no_display,
          username: data.username,
        })
      }
    } catch {
      /* ignore */
    }
  }

  const displayName = userInfo?.username || (userInfo?.registration_no_display ? `#${userInfo.registration_no_display}` : null) || userInfo?.email || ''

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-theme-cream">
        <div className="text-center">
          <div className="animate-spin text-6xl">⏳</div>
          <p className="mt-4 text-theme-dark/90">Loading…</p>
        </div>
      </div>
    )
  }

  const navItemClass =
    'inline-flex items-center justify-center min-w-28 py-2 text-sm font-medium text-theme-dark/90 hover:text-theme-dark hover:underline transition rounded-none'

  const navLinks = (
    <>
      <HeaderActionButtons />
      {displayName && (
        <span className="px-2 text-sm text-theme-dark/90 truncate max-w-[120px] sm:max-w-[180px]" title={userInfo?.email || ''}>
          Hi, {userInfo?.username ? userInfo.username : userInfo?.registration_no_display ? `#${userInfo.registration_no_display}` : userInfo?.email}
        </span>
      )}
      <Link
        href="/dashboard/unclassified"
        onClick={() => setNavOpen(false)}
        className={`${navItemClass} min-h-[44px] sm:min-h-0 relative`}
      >
        Unclassified
        {unclassifiedCount != null && unclassifiedCount > 0 && (
          <span className="absolute -top-1 -right-1 min-w-4 h-4 rounded-full bg-amber-500 text-white text-[10px] font-bold leading-none flex items-center justify-center px-0.5">
            {unclassifiedCount > 99 ? '99+' : unclassifiedCount}
          </span>
        )}
      </Link>
      <Link
        href="/dashboard/categories"
        onClick={() => setNavOpen(false)}
        className={`${navItemClass} min-h-[44px] sm:min-h-0`}
      >
        Categories
      </Link>
      <Link
        href="/home"
        onClick={() => setNavOpen(false)}
        className={`${navItemClass} min-h-[44px] sm:min-h-0`}
      >
        About
      </Link>
      {userInfo && (Number(userInfo.user_class) >= 7) && (
        <Link
          href="/admin/classification-review"
          onClick={() => setNavOpen(false)}
          className={`${navItemClass} min-h-[44px] sm:min-h-0`}
        >
          Admin Portal
        </Link>
      )}
      <button
        onClick={() => { setNavOpen(false); handleLogout() }}
        className={`${navItemClass} min-h-[44px] sm:min-h-0 w-full sm:w-auto sm:min-w-28 text-left sm:justify-center`}
      >
        Log out
      </button>
      <button
        type="button"
        onClick={() => { setNavOpen(false); setSettingsOpen((o) => !o) }}
        className="inline-flex items-center justify-center rounded-lg border-2 border-theme-mid/40 bg-white text-theme-dark hover:bg-theme-light-gray/50 min-h-[44px] min-w-[44px] sm:min-h-0 sm:min-w-0 w-auto sm:w-9 h-auto sm:h-9 px-3 sm:px-0"
        aria-label="Settings"
        title="Settings"
      >
        <span className="sm:hidden text-sm font-medium">setting</span>
        <span className="hidden sm:inline text-lg" aria-hidden>⚙️</span>
      </button>
    </>
  )

  return (
    <DashboardActionsProvider>
      <div className="min-h-screen bg-theme-cream">
        <header className="sticky top-0 z-20 bg-white shadow border-b border-theme-light-gray/50">
          <div className="max-w-7xl mx-auto px-4 py-3 sm:py-4 sm:px-6 lg:px-8 flex justify-between items-center gap-4">
            <h1 className="font-heading text-xl font-bold text-theme-dark truncate min-w-0">
              <Link href="/dashboard" className="hover:text-theme-orange hover:underline" onClick={() => setNavOpen(false)}>LedgerLens</Link>
            </h1>
            {/* Desktop nav */}
            <nav className="hidden sm:flex items-center gap-2 lg:gap-4">
              {navLinks}
            </nav>
          {/* Mobile: hamburger + overlay nav */}
          <button
            type="button"
            onClick={() => setNavOpen((o) => !o)}
            className="sm:hidden p-2 rounded-lg text-theme-dark/90 hover:bg-theme-cream-f0 min-h-[44px] min-w-[44px] flex items-center justify-center"
            aria-label="Toggle menu"
          >
            {navOpen ? (
              <span className="text-xl">✕</span>
            ) : (
              <span className="text-xl">☰</span>
            )}
          </button>
        </div>
        {navOpen && (
          <div className="sm:hidden border-t border-theme-ivory-dark bg-white px-2 py-2 flex flex-col gap-1">
            {navLinks}
          </div>
        )}
      </header>
      <div className="min-h-[calc(100vh-4rem)] sm:min-h-0">
        <AuthProvider>{children}</AuthProvider>
      </div>

      {/* Settings dropdown: only "Edit username" for now */}
      {settingsOpen && (
        <div
          className="fixed inset-0 z-10 sm:z-30"
          aria-hidden
          onClick={() => setSettingsOpen(false)}
        />
      )}
      {settingsOpen && (
        <div className="fixed right-4 top-16 z-20 sm:z-40 bg-white rounded-lg shadow-lg border border-theme-light-gray/50 py-1 min-w-[160px]">
          <button
            type="button"
            className="w-full px-4 py-2 text-left text-sm text-theme-dark hover:bg-theme-light-gray/50"
            onClick={() => { setUsernameModalOpen(true); setSettingsOpen(false) }}
          >
            {userInfo?.username ? 'Edit username' : 'Set username'}
          </button>
        </div>
      )}

      {/* Set username modal */}
      {usernameModalOpen && (
        <UsernameModal
          currentUsername={userInfo?.username ?? ''}
          onClose={() => setUsernameModalOpen(false)}
          onSuccess={async () => {
            await refetchUser()
            setUsernameModalOpen(false)
          }}
        />
      )}
    </div>
    </DashboardActionsProvider>
  )
}

function UsernameModal({
  currentUsername,
  onClose,
  onSuccess,
}: {
  currentUsername: string
  onClose: () => void
  onSuccess: () => void
}) {
  const apiBaseUrl = useApiUrl()
  const [value, setValue] = useState(currentUsername)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    const username = value.trim()
    if (!username) {
      setError('Username cannot be empty')
      return
    }
    if (username.length > 64) {
      setError('Username too long (max 64 characters)')
      return
    }
    if (!/^[a-zA-Z0-9._-]+$/.test(username)) {
      setError('Only letters, numbers, . _ - allowed')
      return
    }
    setLoading(true)
    try {
      const auth = getFirebaseAuth()
      const token = await auth.currentUser?.getIdToken()
      if (!token) {
        setError('Not signed in')
        return
      }
      const res = await fetch(`${apiBaseUrl}/api/auth/me`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ username }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        setError(data.detail || (res.status === 409 ? 'Username already taken' : 'Failed to update'))
        return
      }
      onSuccess()
    } catch {
      setError('Network error')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={onClose}>
      <div className="bg-white rounded-xl shadow-xl border border-theme-light-gray/50 max-w-sm w-full p-6" onClick={(e) => e.stopPropagation()}>
        <h3 className="font-heading text-lg font-semibold text-theme-dark mb-2">Set your username</h3>
        <p className="text-sm text-theme-dark/90 mb-4">Unique name for greeting and future feedback. Letters, numbers, . _ - only.</p>
        <form onSubmit={handleSubmit}>
          <input
            type="text"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="e.g. alice_2024"
            className="w-full px-3 py-2 border border-theme-mid rounded-lg focus:ring-2 focus:ring-theme-orange focus:border-theme-orange"
            maxLength={64}
            autoFocus
          />
          {error && <p className="mt-2 text-sm text-theme-red">{error}</p>}
          <div className="mt-4 flex gap-2 justify-end">
            <button type="button" onClick={onClose} className="px-4 py-2 text-theme-dark/90 hover:bg-theme-cream-f0 rounded-lg">
              Cancel
            </button>
            <button type="submit" disabled={loading} className="px-4 py-2 btn-primary disabled:opacity-50">
              {loading ? 'Saving…' : 'Save'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
