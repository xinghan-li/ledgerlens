'use client'

import { useEffect, useState } from 'react'
import { getFirebaseAuth } from '@/lib/firebase'
import { onAuthStateChanged } from 'firebase/auth'
import Link from 'next/link'

const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

type Row = {
  id: string
  user_id: string
  uploaded_at: string
  current_status: string
  current_stage: string | null
  raw_file_url: string | null
  failure_reason: string
  run_stage?: string | null
  run_provider?: string | null
}

export default function FailedReceiptsListPage() {
  const [rows, setRows] = useState<Row[]>([])
  const [total, setTotal] = useState(0)
  const [limit] = useState(50)
  const [offset, setOffset] = useState(0)
  const [loading, setLoading] = useState(true)
  const [token, setToken] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const auth = getFirebaseAuth()
    const unsubscribe = onAuthStateChanged(auth, async (user) => {
      setToken(user ? await user.getIdToken() : null)
    })
    return () => unsubscribe()
  }, [])

  const fetchList = async () => {
    if (!token) return
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams({ limit: String(limit), offset: String(offset) })
      const res = await fetch(`${apiUrl}/api/admin/failed-receipts?${params}`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (!res.ok) throw new Error(res.status === 403 ? '无权限' : await res.text())
      const data = await res.json()
      setRows(data.data || [])
      setTotal(data.total ?? 0)
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (token) fetchList()
  }, [token, offset])

  const formatDate = (s: string) => {
    try {
      return new Date(s).toLocaleString()
    } catch {
      return s
    }
  }

  const [deletingId, setDeletingId] = useState<string | null>(null)
  const handleDelete = async (id: string) => {
    if (!confirm('确定要永久删除这条失败小票吗？此操作不可恢复。')) return
    if (!token) return
    setDeletingId(id)
    try {
      const res = await fetch(`${apiUrl}/api/admin/failed-receipts/${id}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` },
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data.detail || res.statusText)
      }
      await fetchList()
    } catch (e) {
      setError(e instanceof Error ? e.message : '删除失败')
    } finally {
      setDeletingId(null)
    }
  }

  if (!token) {
    return <div className="text-center py-8 text-gray-500">请先登录</div>
  }

  return (
    <div>
      <h2 className="text-lg font-semibold mb-4">失败小票 (Failed Receipts)</h2>
      <p className="text-sm text-gray-600 mb-4">点击一行进入手动修正页面</p>
      {error && (
        <div className="mb-4 p-2 bg-red-100 text-red-700 rounded text-sm flex items-center justify-between gap-2">
          <span>{error}</span>
          <button type="button" className="shrink-0 text-red-700 hover:text-red-900" onClick={() => setError(null)} aria-label="关闭">×</button>
        </div>
      )}
      {loading ? (
        <p className="text-gray-500">加载中...</p>
      ) : (
        <div className="overflow-x-auto bg-white rounded-lg shadow">
          <table className="min-w-full divide-y divide-gray-200 text-sm">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-3 py-2 text-left">上传时间</th>
                <th className="px-3 py-2 text-left">状态 / 阶段</th>
                <th className="px-3 py-2 text-left">失败原因</th>
                <th className="px-3 py-2 text-left">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {rows.map((r) => (
                <tr key={r.id} className="hover:bg-gray-50">
                  <td className="px-3 py-2">{formatDate(r.uploaded_at)}</td>
                  <td className="px-3 py-2">
                    <span className="text-red-600">{r.current_status}</span>
                    {r.current_stage && <span className="text-gray-500 ml-1">/ {r.current_stage}</span>}
                  </td>
                  <td className="px-3 py-2 max-w-md truncate text-gray-700" title={r.failure_reason}>
                    {r.failure_reason}
                  </td>
                  <td className="px-3 py-2 flex items-center gap-3">
                    <Link
                      href={`/admin/failed-receipts/${r.id}`}
                      className="text-blue-600 hover:underline"
                    >
                      修正
                    </Link>
                    <button
                      type="button"
                      onClick={() => handleDelete(r.id)}
                      disabled={deletingId === r.id}
                      className="text-red-600 hover:underline disabled:opacity-50"
                    >
                      {deletingId === r.id ? '删除中…' : '删除'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {rows.length === 0 && !loading && (
        <p className="text-gray-500 mt-4">暂无失败或待审核的小票</p>
      )}
      {total > limit && (
        <div className="mt-4 flex gap-2">
          <button className="px-3 py-1 border rounded disabled:opacity-50" disabled={offset === 0} onClick={() => setOffset((o) => Math.max(0, o - limit))}>
            上一页
          </button>
          <button className="px-3 py-1 border rounded disabled:opacity-50" disabled={offset + limit >= total} onClick={() => setOffset((o) => o + limit)}>
            下一页
          </button>
        </div>
      )}
    </div>
  )
}
