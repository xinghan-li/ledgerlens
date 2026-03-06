'use client'

import { useEffect, useState } from 'react'
import { getFirebaseAuth } from '@/lib/firebase'
import { onAuthStateChanged } from 'firebase/auth'
import { useApiUrl } from '@/lib/api-url-context'

const USER_CLASS_OPTIONS: { value: number; label: string }[] = [
  { value: 0, label: 'Free (0)' },
  { value: 2, label: 'Premium (2)' },
  { value: 7, label: 'Admin (7)' },
  { value: 9, label: 'Super Admin (9)' },
]

/** Options allowed for current admin: only tiers strictly lower than currentUserClass (e.g. 9 → [0,2,7], 7 → [0,2]) */
function allowedTierOptions(currentUserClass: number) {
  return USER_CLASS_OPTIONS.filter((o) => o.value < currentUserClass)
}

type UserRow = {
  id: string
  email: string | null
  user_class: number
  user_name: string | null
  registration_no: number | null
  status: string | null
  created_at: string
}

export default function UserManagementPage() {
  const apiBaseUrl = useApiUrl()
  const [rows, setRows] = useState<UserRow[]>([])
  const [total, setTotal] = useState(0)
  const [currentUserClass, setCurrentUserClass] = useState<number>(0)
  const [limit] = useState(100)
  const [offset, setOffset] = useState(0)
  const [loading, setLoading] = useState(true)
  const [token, setToken] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [updatingId, setUpdatingId] = useState<string | null>(null)

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
      const res = await fetch(`${apiBaseUrl}/api/admin/users?${params}`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (!res.ok) throw new Error(res.status === 403 ? 'Forbidden' : await res.text())
      const data = await res.json()
      setRows(data.data || [])
      setTotal(data.total ?? 0)
      setCurrentUserClass(data.current_user_class ?? 0)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (token) fetchList()
  }, [token, offset])

  const handleClassChange = async (userId: string, user_class: number) => {
    if (!token) return
    setUpdatingId(userId)
    try {
      const res = await fetch(`${apiBaseUrl}/api/admin/users/${userId}`, {
        method: 'PATCH',
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ user_class }),
      })
      if (!res.ok) throw new Error(await res.text())
      setRows((prev) => prev.map((r) => (r.id === userId ? { ...r, user_class } : r)))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Update failed')
    } finally {
      setUpdatingId(null)
    }
  }

  const formatDate = (s: string) => {
    try {
      return new Date(s).toLocaleString()
    } catch {
      return s
    }
  }

  const editableOptions = allowedTierOptions(currentUserClass)

  return (
    <div className="space-y-4">
      <h2 className="font-heading text-xl font-semibold text-theme-dark">User Management</h2>

      <div className="rounded-lg border border-theme-light-gray/50 bg-theme-cream/50 p-4 text-sm text-theme-dark">
        <p className="font-medium text-theme-dark/90 mb-2">Note — Tier meanings</p>
        <ul className="list-disc list-inside space-y-1 text-theme-mid">
          <li><strong>0</strong> = Free</li>
          <li><strong>2</strong> = Premium</li>
          <li><strong>7</strong> = Admin</li>
          <li><strong>9</strong> = Super Admin</li>
        </ul>
        <p className="mt-2 text-theme-mid">You may only set users to a tier lower than your own (e.g. if you are 9, you can set others up to 7, not 9). New users default to 0.</p>
      </div>

      {error && (
        <div className="p-3 bg-theme-red/10 border border-theme-red/30 rounded-lg text-theme-red text-sm">
          {error}
        </div>
      )}

      {loading ? (
        <p className="text-theme-mid">Loading…</p>
      ) : (
        <>
          <div className="overflow-x-auto rounded-lg border border-theme-light-gray/50">
            <table className="min-w-full divide-y divide-theme-light-gray/50">
              <thead className="bg-theme-light-gray/30">
                <tr>
                  <th className="px-3 py-2 text-left text-sm font-medium text-theme-dark">Email</th>
                  <th className="px-3 py-2 text-left text-sm font-medium text-theme-dark">Name</th>
                  <th className="px-3 py-2 text-left text-sm font-medium text-theme-dark">Tier</th>
                  <th className="px-3 py-2 text-left text-sm font-medium text-theme-dark">Reg #</th>
                  <th className="px-3 py-2 text-left text-sm font-medium text-theme-dark">Status</th>
                  <th className="px-3 py-2 text-left text-sm font-medium text-theme-dark">Created</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-theme-light-gray/30 bg-white">
                {rows.map((r) => (
                  <tr key={r.id} className="hover:bg-theme-cream/30">
                    <td className="px-3 py-2 text-sm text-theme-dark truncate max-w-[200px]" title={r.email ?? ''}>
                      {r.email ?? '—'}
                    </td>
                    <td className="px-3 py-2 text-sm text-theme-dark">{r.user_name ?? '—'}</td>
                    <td className="px-3 py-2">
                      {r.user_class >= currentUserClass ? (
                        <span className="text-sm text-theme-mid" title="Cannot edit users at or above your tier">
                          {USER_CLASS_OPTIONS.find((o) => o.value === r.user_class)?.label ?? `Tier ${r.user_class}`}
                        </span>
                      ) : (
                        <>
                          <select
                            value={r.user_class}
                            onChange={(e) => handleClassChange(r.id, Number(e.target.value))}
                            disabled={updatingId === r.id}
                            className="text-sm border border-theme-mid/40 rounded px-2 py-1 bg-white text-theme-dark"
                          >
                            {editableOptions.map((o) => (
                              <option key={o.value} value={o.value}>
                                {o.label}
                              </option>
                            ))}
                          </select>
                          {updatingId === r.id && <span className="ml-1 text-theme-mid text-xs">Saving…</span>}
                        </>
                      )}
                    </td>
                    <td className="px-3 py-2 text-sm text-theme-mid">{r.registration_no ?? '—'}</td>
                    <td className="px-3 py-2 text-sm text-theme-mid">{r.status ?? '—'}</td>
                    <td className="px-3 py-2 text-sm text-theme-mid">{formatDate(r.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-theme-mid text-sm">
            Showing {rows.length} of {total} users.
          </p>
        </>
      )}
    </div>
  )
}
