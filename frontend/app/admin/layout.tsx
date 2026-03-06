'use client'

import { useEffect, useState } from 'react'
import { useRouter, usePathname } from 'next/navigation'
import Link from 'next/link'
import { onAuthStateChanged } from 'firebase/auth'
import { getFirebaseAuth, getAuthToken } from '@/lib/firebase'
import { useApiUrl } from '@/lib/api-url-context'

export default function AdminLayout({
  children,
}: {
  children: React.ReactNode
}) {
  const router = useRouter()
  const pathname = usePathname()
  const apiBaseUrl = useApiUrl()
  const [allowed, setAllowed] = useState<boolean | null>(null)

  useEffect(() => {
    const auth = getFirebaseAuth()
    const unsubscribe = onAuthStateChanged(auth, async (user) => {
      if (!user) {
        router.push('/login')
        return
      }
      const token = await getAuthToken()
      if (!token) {
        router.push('/login')
        return
      }
      try {
        const res = await fetch(`${apiBaseUrl}/api/admin/classification-review?limit=1`, {
          headers: { Authorization: `Bearer ${token}` },
        })
        if (res.status === 403) {
          setAllowed(false)
          return
        }
        if (res.ok) {
          setAllowed(true)
          return
        }
        setAllowed(false)
      } catch {
        setAllowed(false)
      }
    })
    return () => unsubscribe()
  }, [router, apiBaseUrl])

  if (allowed === null) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-theme-cream">
        <div className="text-center">
          <div className="animate-spin text-6xl">⏳</div>
          <p className="mt-4 text-theme-dark/90">Checking permissions…</p>
        </div>
      </div>
    )
  }

  if (!allowed) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-theme-cream">
        <div className="text-center">
          <p className="text-theme-red font-medium">Admin or Super Admin role required.</p>
          <Link href="/dashboard" className="mt-4 inline-block text-theme-orange hover:underline">Back to Dashboard</Link>
        </div>
      </div>
    )
  }

  const navItemClass =
    'inline-flex items-center justify-center min-w-40 py-2 text-sm font-medium text-theme-dark/90 hover:text-theme-dark hover:underline transition rounded-none'

  return (
    <div className="min-h-screen bg-theme-cream">
      <header className="bg-white shadow border-b border-theme-light-gray/50">
        <div className="max-w-7xl mx-auto px-4 py-3 sm:py-4 sm:px-6 lg:px-8 flex justify-between items-center gap-4">
          <h1 className="font-heading text-xl font-bold text-theme-dark truncate min-w-0">
            <Link href="/admin/classification-review" className="hover:text-theme-orange hover:underline">Admin Portal</Link>
          </h1>
          <nav className="flex items-center gap-2 lg:gap-4">
            <Link
              href="/admin/classification-review"
              className={`${navItemClass} ${pathname?.includes('classification-review') ? 'text-theme-dark underline' : ''}`}
            >
              Classification Review
            </Link>
            <Link
              href="/admin/categories"
              className={`${navItemClass} ${pathname?.includes('categories') ? 'text-theme-dark underline' : ''}`}
            >
              Categories
            </Link>
            <Link
              href="/admin/store-review"
              className={`${navItemClass} ${pathname?.includes('store-review') ? 'text-theme-dark underline' : ''}`}
            >
              Store Review
            </Link>
            <Link
              href="/admin/failed-receipts"
              className={`${navItemClass} ${pathname?.includes('failed-receipts') ? 'text-theme-dark underline' : ''}`}
            >
              Failed Receipts
            </Link>
            <Link href="/dashboard" className={navItemClass}>Dashboard</Link>
          </nav>
        </div>
      </header>
      <main className="max-w-7xl mx-auto px-4 py-6 sm:px-6 lg:px-8">
        {children}
      </main>
    </div>
  )
}
