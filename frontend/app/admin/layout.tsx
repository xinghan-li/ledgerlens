'use client'

import { useEffect, useState } from 'react'
import { useRouter, usePathname } from 'next/navigation'
import Link from 'next/link'
import { getAuthToken } from '@/lib/firebase'

const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

export default function AdminLayout({
  children,
}: {
  children: React.ReactNode
}) {
  const router = useRouter()
  const pathname = usePathname()
  const [allowed, setAllowed] = useState<boolean | null>(null)

  useEffect(() => {
    const check = async () => {
      const token = await getAuthToken()
      if (!token) {
        router.push('/login')
        return
      }
      try {
        const res = await fetch(`${apiUrl}/api/admin/classification-review?limit=1`, {
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
    }
    check()
  }, [router])

  if (allowed === null) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-center">
          <div className="animate-spin text-6xl">⏳</div>
          <p className="mt-4 text-gray-600">检查权限...</p>
        </div>
      </div>
    )
  }

  if (!allowed) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-center">
          <p className="text-red-600 font-medium">需要 Admin 或 Super Admin 权限</p>
          <Link href="/dashboard" className="mt-4 inline-block text-blue-600 hover:underline">返回 Dashboard</Link>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white shadow">
        <div className="max-w-7xl mx-auto px-4 py-3 sm:px-6 lg:px-8 flex justify-between items-center">
          <h1 className="text-xl font-bold text-gray-900">Admin</h1>
          <nav className="flex gap-4">
            <Link
              href="/admin/classification-review"
              className={`px-3 py-1 rounded ${pathname?.includes('classification-review') ? 'bg-gray-200' : 'hover:bg-gray-100'}`}
            >
              分类审核
            </Link>
            <Link
              href="/admin/categories"
              className={`px-3 py-1 rounded ${pathname?.includes('categories') ? 'bg-gray-200' : 'hover:bg-gray-100'}`}
            >
              分类管理
            </Link>
            <Link
              href="/admin/store-review"
              className={`px-3 py-1 rounded ${pathname?.includes('store-review') ? 'bg-gray-200' : 'hover:bg-gray-100'}`}
            >
              门店审核
            </Link>
            <Link
              href="/admin/failed-receipts"
              className={`px-3 py-1 rounded ${pathname?.includes('failed-receipts') ? 'bg-gray-200' : 'hover:bg-gray-100'}`}
            >
              失败小票
            </Link>
            <Link href="/dashboard" className="px-3 py-1 rounded hover:bg-gray-100">Dashboard</Link>
          </nav>
        </div>
      </header>
      <main className="max-w-7xl mx-auto px-4 py-6 sm:px-6 lg:px-8">
        {children}
      </main>
    </div>
  )
}
