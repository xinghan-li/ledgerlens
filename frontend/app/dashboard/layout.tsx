'use client'

import { useEffect, useState } from 'react'
import { useRouter, usePathname } from 'next/navigation'
import Link from 'next/link'
import { getFirebaseAuth } from '@/lib/firebase'
import { onAuthStateChanged, signOut } from 'firebase/auth'

const apiUrl = () => process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

type UserInfo = {
  user_id: string
  email: string
  user_class: string
  registration_no?: number
  registration_no_display?: string
  username?: string | null
} | null

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode
}) {
  const router = useRouter()
  const pathname = usePathname()
  const [userInfo, setUserInfo] = useState<UserInfo>(null)
  const [loading, setLoading] = useState(true)
  const [navOpen, setNavOpen] = useState(false)
  const [mounted, setMounted] = useState(false)
  const [usernameModalOpen, setUsernameModalOpen] = useState(false)

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
        const res = await fetch(`${apiUrl()}/api/auth/me`, {
          headers: { Authorization: `Bearer ${token}` },
        })
        if (res.ok) {
          const data = await res.json()
          setUserInfo({
            user_id: data.user_id,
            email: data.email,
            user_class: data.user_class,
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
  }, [router])

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
      const res = await fetch(`${apiUrl()}/api/auth/me`, { headers: { Authorization: `Bearer ${token}` } })
      if (res.ok) {
        const data = await res.json()
        setUserInfo({
          user_id: data.user_id,
          email: data.email,
          user_class: data.user_class,
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
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-center">
          <div className="animate-spin text-6xl">⏳</div>
          <p className="mt-4 text-gray-600">Loading…</p>
        </div>
      </div>
    )
  }

  const navLinks = (
    <>
      {displayName && (
        <span className="px-2 text-sm text-gray-600 truncate max-w-[120px] sm:max-w-[180px]" title={userInfo?.email || ''}>
          Hi, {userInfo?.username ? userInfo.username : userInfo?.registration_no_display ? `#${userInfo.registration_no_display}` : userInfo?.email}
        </span>
      )}
      <button
        type="button"
        onClick={() => { setNavOpen(false); setUsernameModalOpen(true) }}
        className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900 hover:bg-gray-100 rounded-lg transition"
      >
        {userInfo?.username ? 'Edit username' : 'Set username'}
      </button>
      {userInfo?.user_class === 'super_admin' && (
        <Link
          href="/dashboard/developer"
          onClick={() => setNavOpen(false)}
          className={`flex items-center px-4 py-3 sm:py-2 text-sm font-medium rounded-lg transition min-h-[44px] sm:min-h-0 ${
            mounted && pathname === '/dashboard/developer'
              ? 'bg-gray-200 text-gray-900'
              : 'text-gray-700 hover:text-gray-900 hover:bg-gray-100'
          }`}
        >
          Developer
        </Link>
      )}
      <Link
        href="/admin/classification-review"
        onClick={() => setNavOpen(false)}
        className="flex items-center px-4 py-3 sm:py-2 text-sm font-medium text-gray-700 hover:text-gray-900 hover:bg-gray-100 rounded-lg transition min-h-[44px] sm:min-h-0"
      >
        Admin
      </Link>
      <button
        onClick={() => { setNavOpen(false); handleLogout() }}
        className="w-full text-left px-4 py-3 sm:py-2 text-sm font-medium text-gray-700 hover:text-gray-900 hover:bg-gray-100 rounded-lg transition min-h-[44px] sm:min-h-0 flex items-center"
      >
        Log out
      </button>
    </>
  )

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white shadow">
        <div className="max-w-7xl mx-auto px-4 py-3 sm:py-4 sm:px-6 lg:px-8 flex justify-between items-center gap-4">
          <h1 className="text-xl sm:text-2xl font-bold text-gray-900 truncate min-w-0">
            <Link href="/dashboard" className="hover:text-gray-700" onClick={() => setNavOpen(false)}>LedgerLens</Link>
          </h1>
          {/* Desktop nav */}
          <nav className="hidden sm:flex items-center gap-2 lg:gap-4">
            {navLinks}
          </nav>
          {/* Mobile: hamburger + overlay nav */}
          <button
            type="button"
            onClick={() => setNavOpen((o) => !o)}
            className="sm:hidden p-2 rounded-lg text-gray-700 hover:bg-gray-100 min-h-[44px] min-w-[44px] flex items-center justify-center"
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
          <div className="sm:hidden border-t border-gray-200 bg-white px-2 py-2 flex flex-col gap-1">
            {navLinks}
          </div>
        )}
      </header>
      <div className="min-h-[calc(100vh-4rem)] sm:min-h-0">{children}</div>

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
  const [value, setValue] = useState(currentUsername)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const apiUrl = () => process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

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
      const res = await fetch(`${apiUrl()}/api/auth/me`, {
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
      <div className="bg-white rounded-xl shadow-xl max-w-sm w-full p-6" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-lg font-semibold text-gray-900 mb-2">Set your username</h3>
        <p className="text-sm text-gray-600 mb-4">Unique name for greeting and future feedback. Letters, numbers, . _ - only.</p>
        <form onSubmit={handleSubmit}>
          <input
            type="text"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="e.g. alice_2024"
            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            maxLength={64}
            autoFocus
          />
          {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
          <div className="mt-4 flex gap-2 justify-end">
            <button type="button" onClick={onClose} className="px-4 py-2 text-gray-700 hover:bg-gray-100 rounded-lg">
              Cancel
            </button>
            <button type="submit" disabled={loading} className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50">
              {loading ? 'Saving…' : 'Save'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
