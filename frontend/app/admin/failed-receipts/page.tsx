'use client'

import { useEffect, useState } from 'react'
import { getFirebaseAuth } from '@/lib/firebase'
import { onAuthStateChanged } from 'firebase/auth'
import Link from 'next/link'
import { useApiUrl } from '@/lib/api-url-context'

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
  admin_failure_kind?: string | null
  failure_kind_label: string
  escalation_notes?: string | null
}

export default function FailedReceiptsListPage() {
  const apiBaseUrl = useApiUrl()
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
      const res = await fetch(`${apiBaseUrl}/api/admin/failed-receipts?${params}`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (!res.ok) throw new Error(res.status === 403 ? 'Forbidden' : await res.text())
      const data = await res.json()
      setRows(data.data || [])
      setTotal(data.total ?? 0)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load')
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
    if (!confirm('Permanently delete this failed receipt? This cannot be undone.')) return
    if (!token) return
    setDeletingId(id)
    try {
      const res = await fetch(`${apiBaseUrl}/api/admin/failed-receipts/${id}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` },
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data.detail || res.statusText)
      }
      await fetchList()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Delete failed')
    } finally {
      setDeletingId(null)
    }
  }

  if (!token) {
    return <div className="text-center py-8 text-theme-mid">Please sign in first.</div>
  }

  return (
    <div>
      <h2 className="text-lg font-semibold mb-4">Failed Receipts</h2>
      <p className="text-sm text-theme-dark/90 mb-4">Click a row to open the manual correction page.</p>
      {error && (
        <div className="mb-4 p-2 bg-theme-red/15 text-theme-red rounded text-sm flex items-center justify-between gap-2">
          <span>{error}</span>
          <button type="button" className="shrink-0 text-theme-red hover:opacity-90" onClick={() => setError(null)} aria-label="Close">×</button>
        </div>
      )}
      {loading ? (
        <p className="text-theme-mid">Loading…</p>
      ) : (
        <div className="overflow-x-auto bg-white rounded-lg shadow">
          <table className="min-w-full divide-y divide-theme-light-gray text-sm">
            <thead className="bg-theme-cream/80">
              <tr>
                <th className="px-3 py-2 text-left">Uploaded</th>
                <th className="px-3 py-2 text-left">Kind</th>
                <th className="px-3 py-2 text-left">Status / Stage</th>
                <th className="px-3 py-2 text-left">Failure reason</th>
                <th className="px-3 py-2 text-left">User notes</th>
                <th className="px-3 py-2 text-left">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-theme-light-gray">
              {rows.map((r) => (
                <tr key={r.id} className="hover:bg-theme-cream/80">
                  <td className="px-3 py-2">{formatDate(r.uploaded_at)}</td>
                  <td className="px-3 py-2">
                    <span className="text-xs font-medium text-theme-orange">{r.failure_kind_label ?? '—'}</span>
                  </td>
                  <td className="px-3 py-2">
                    <span className="text-theme-red">{r.current_status}</span>
                    {r.current_stage && <span className="text-theme-mid ml-1">/ {r.current_stage}</span>}
                  </td>
                  <td className="px-3 py-2 max-w-md truncate text-theme-dark/90" title={r.failure_reason}>
                    {r.failure_reason}
                  </td>
                  <td className="px-3 py-2 max-w-xs truncate text-theme-dark/80" title={r.escalation_notes ?? ''}>
                    {r.escalation_notes ?? '—'}
                  </td>
                  <td className="px-3 py-2 flex items-center gap-3">
                    <Link
                      href={`/admin/failed-receipts/${r.id}`}
                      className="text-theme-orange hover:underline"
                    >
                      Correct
                    </Link>
                    <button
                      type="button"
                      onClick={() => handleDelete(r.id)}
                      disabled={deletingId === r.id}
                      className="text-theme-red hover:underline disabled:opacity-50"
                    >
                      {deletingId === r.id ? 'Deleting…' : 'Delete'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {rows.length === 0 && !loading && (
        <p className="text-theme-mid mt-4">No failed or pending receipts.</p>
      )}
      {total > limit && (
        <div className="mt-4 flex gap-2">
          <button className="px-3 py-1 border rounded disabled:opacity-50" disabled={offset === 0} onClick={() => setOffset((o) => Math.max(0, o - limit))}>
            Previous
          </button>
          <button className="px-3 py-1 border rounded disabled:opacity-50" disabled={offset + limit >= total} onClick={() => setOffset((o) => o + limit)}>
            Next
          </button>
        </div>
      )}
    </div>
  )
}
