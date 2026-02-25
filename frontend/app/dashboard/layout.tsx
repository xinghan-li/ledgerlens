'use client'

import { useEffect, useState } from 'react'
import { useRouter, usePathname } from 'next/navigation'
import Link from 'next/link'
import { getFirebaseAuth } from '@/lib/firebase'
import { onAuthStateChanged, signOut } from 'firebase/auth'

const apiUrl = () => process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

type UserInfo = { user_id: string; email: string; user_class: string } | null

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
          setUserInfo({ user_id: data.user_id, email: data.email, user_class: data.user_class })
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
    </div>
  )
}
