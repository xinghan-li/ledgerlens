'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { useApiUrl } from '@/lib/api-url-context'
import { useAuth } from '@/lib/auth-context'

type UnclassifiedItem = {
  receipt_id: string
  record_item_id: string
  receipt_date: string | null
  store_display_name: string
  store_address: string | null
  product_name: string
  line_total_cents: number | null
  user_marked_idk?: boolean
}

type Cat = { id: string; name: string; parent_id: string | null }

type DismissReason = 'incorrect_item' | 'other'

type DismissModal = {
  item: UnclassifiedItem
  reason: DismissReason | null
  comment: string
  submitting: boolean
  error: string | null
}

function formatDollars(cents: number | null): string {
  if (cents == null) return '—'
  return (cents / 100).toLocaleString('en-US', { style: 'currency', currency: 'USD' })
}

function formatDate(d: string | null): string {
  if (!d) return '—'
  try {
    const [y, m, day] = d.split('-')
    return [m, day, y].filter(Boolean).join('/')
  } catch {
    return d
  }
}

/** Show only the city/state portion of an address, e.g. "19715 Highway 99, Lynnwood, WA 98036" → "Lynnwood, WA" */
function cityFromAddress(addr: string): string {
  const parts = addr.split(',').map((s) => s.trim())
  if (parts.length >= 3) {
    // Last part usually "WA 98036" → take state abbreviation only
    const stateZip = parts[parts.length - 1].replace(/\s*\d{5}(-\d{4})?$/, '').trim()
    const city = parts[parts.length - 2]
    return stateZip ? `${city}, ${stateZip}` : city
  }
  return parts[parts.length - 1] ?? addr
}

function StoreCell({ name, address }: { name: string; address: string | null }) {
  const [expanded, setExpanded] = useState(false)
  return (
    <div className="min-w-0">
      <span className="font-medium text-theme-dark leading-snug block">{name}</span>
      {address && (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="text-xs text-theme-mid/80 hover:text-theme-mid mt-0.5 text-left leading-tight"
        >
          {expanded ? (
            <span className="whitespace-pre-line">{address}</span>
          ) : (
            <span>{cityFromAddress(address)}</span>
          )}
        </button>
      )}
    </div>
  )
}

export default function UnclassifiedPage() {
  const apiBaseUrl = useApiUrl()
  const auth = useAuth()
  const [items, setItems] = useState<UnclassifiedItem[]>([])
  const [categories, setCategories] = useState<Cat[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [savingId, setSavingId] = useState<string | null>(null)
  const [editL1, setEditL1] = useState<Record<string, string>>({})
  const [editL2, setEditL2] = useState<Record<string, string>>({})
  const [editL3, setEditL3] = useState<Record<string, string>>({})
  const [dismissModal, setDismissModal] = useState<DismissModal | null>(null)
  const commentRef = useRef<HTMLTextAreaElement>(null)

  const fetchUnclassified = useCallback(async () => {
    if (!auth?.token) return
    try {
      const res = await fetch(`${apiBaseUrl}/api/me/unclassified`, {
        headers: { Authorization: `Bearer ${auth.token}` },
      })
      if (res.ok) {
        const data = await res.json()
        setItems(Array.isArray(data) ? data : [])
        setError(null)
      } else {
        const text = await res.text()
        let detail = text
        try {
          const j = JSON.parse(text)
          if (typeof j?.detail === 'string') detail = j.detail
          else if (text.length > 200) detail = `${text.slice(0, 200)}…`
        } catch {
          if (text.length > 200) detail = `${text.slice(0, 200)}…`
        }
        setError(`Request failed (${res.status}): ${detail || 'Failed to load unclassified items'}`)
      }
    } catch (e) {
      setError((e as Error).message || 'Network error')
    }
  }, [apiBaseUrl, auth?.token])

  const fetchCategories = useCallback(async () => {
    if (!auth?.token) return
    try {
      const res = await fetch(`${apiBaseUrl}/api/categories`, {
        headers: { Authorization: `Bearer ${auth.token}` },
      })
      if (res.ok) {
        const json = await res.json()
        setCategories(json?.data ?? [])
      }
    } catch (_) {}
  }, [apiBaseUrl, auth?.token])

  useEffect(() => {
    if (!auth?.token) {
      setLoading(false)
      return
    }
    setLoading(true)
    setError(null)
    Promise.all([fetchUnclassified(), fetchCategories()]).finally(() => setLoading(false))
  }, [auth?.token, fetchUnclassified, fetchCategories])

  useEffect(() => {
    if (!auth?.token) return
    fetch(`${apiBaseUrl}/api/me/idk-now-classified`, { headers: { Authorization: `Bearer ${auth.token}` } })
      .then((r) => r.ok ? r.json() : null)
      .then((data) => {
        if (data?.record_item_ids?.length) fetchUnclassified()
      })
      .catch(() => {})
  }, [auth?.token, apiBaseUrl, fetchUnclassified])

  const confirmCategory = async (item: UnclassifiedItem) => {
    const id = item.record_item_id
    const cid = editL3[id] || editL2[id] || editL1[id]
    if (!cid || !item.receipt_id || !auth?.token) return
    setSavingId(id)
    try {
      const res = await fetch(
        `${apiBaseUrl}/api/receipt/${item.receipt_id}/item/${id}/category`,
        {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${auth.token}` },
          body: JSON.stringify({ category_id: cid }),
        }
      )
      if (res.ok) {
        setEditL1((o) => { const n = { ...o }; delete n[id]; return n })
        setEditL2((o) => { const n = { ...o }; delete n[id]; return n })
        setEditL3((o) => { const n = { ...o }; delete n[id]; return n })
        await fetchUnclassified()
      } else {
        const err = await res.json().catch(() => ({}))
        setError(err?.detail ?? 'Save failed')
      }
    } catch (e) {
      setError((e as Error).message ?? 'Network error')
    } finally {
      setSavingId(null)
    }
  }

  const markIdk = async (item: UnclassifiedItem) => {
    if (!auth?.token) return
    setSavingId(item.record_item_id)
    try {
      const res = await fetch(
        `${apiBaseUrl}/api/me/item/${item.record_item_id}/idk`,
        { method: 'POST', headers: { Authorization: `Bearer ${auth.token}` } }
      )
      if (res.ok) await fetchUnclassified()
    } catch (_) {}
    finally { setSavingId(null) }
  }

  const openDismissModal = (item: UnclassifiedItem) => {
    setDismissModal({ item, reason: null, comment: '', submitting: false, error: null })
  }

  const submitDismiss = async () => {
    if (!dismissModal || !dismissModal.reason || !auth?.token) return
    if (dismissModal.reason === 'other' && !dismissModal.comment.trim()) return
    setDismissModal((m) => m ? { ...m, submitting: true, error: null } : m)
    try {
      const res = await fetch(
        `${apiBaseUrl}/api/me/item/${dismissModal.item.record_item_id}/dismiss`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${auth.token}` },
          body: JSON.stringify({ reason: dismissModal.reason, comment: dismissModal.comment }),
        }
      )
      if (res.ok) {
        setDismissModal(null)
        await fetchUnclassified()
      } else {
        const err = await res.json().catch(() => ({}))
        setDismissModal((m) => m ? { ...m, submitting: false, error: err?.detail ?? 'Delete failed' } : m)
      }
    } catch (e) {
      setDismissModal((m) => m ? { ...m, submitting: false, error: (e as Error).message ?? 'Network error' } : m)
    }
  }

  const L1List = categories.filter((c) => c.parent_id == null)
  const getL2 = (l1Id: string) => categories.filter((c) => c.parent_id === l1Id)
  const getL3 = (l2Id: string) => categories.filter((c) => c.parent_id === l2Id)

  const byDate = items.reduce<Record<string, UnclassifiedItem[]>>((acc, it) => {
    const d = it.receipt_date ?? 'Unknown'
    if (!acc[d]) acc[d] = []
    acc[d].push(it)
    return acc
  }, {})
  const sortedDates = Object.keys(byDate).sort((a, b) => (b > a ? 1 : -1))

  if (!auth?.token) {
    return (
      <div className="p-4">
        <p className="text-theme-mid">Please sign in to view unclassified items.</p>
      </div>
    )
  }

  const isFailedToFetch = error?.toLowerCase().includes('failed to fetch')

  return (
    <div className="p-4 max-w-6xl mx-auto">
      <div className="flex items-center justify-between gap-4 mb-4">
        <h1 className="text-xl font-semibold text-theme-dark">Unclassified items</h1>
        <Link href="/dashboard" className="text-sm text-theme-dark/90 hover:underline shrink-0">Back to dashboard</Link>
      </div>
      <p className="text-sm text-theme-dark/90 mb-4">
        Assign a category (Level I / II / III) and confirm, or click &quot;I don&apos;t know&quot; to skip. Items you mark &quot;I don&apos;t know&quot; will follow backend classification when available.
      </p>

      {loading && (
        <div className="py-8 text-center text-theme-mid">Loading…</div>
      )}
      {error && (
        <div className="text-theme-red text-sm mb-4">
          <p>{isFailedToFetch
            ? 'Cannot reach backend (Failed to fetch). Check that the backend is running and the URL is correct; if using ngrok, ensure the tunnel is open.'
            : error}
          </p>
          <button
            type="button"
            onClick={() => { setError(null); setLoading(true); Promise.all([fetchUnclassified(), fetchCategories()]).finally(() => setLoading(false)) }}
            className="mt-2 text-xs px-2 py-1 rounded border border-theme-red/40 text-theme-red hover:bg-theme-red/10"
          >
            Retry
          </button>
        </div>
      )}
      {!loading && !error && items.length === 0 && (
        <p className="text-theme-mid">No unclassified items.</p>
      )}

      {!loading && items.length > 0 && (
        <div className="space-y-6">
          {sortedDates.map((date) => (
            <div key={date} className="bg-white rounded-xl shadow p-4">
              <h2 className="text-sm font-semibold text-theme-dark/90 mb-3">Date: {formatDate(date)}</h2>
              <div className="overflow-x-auto">
                <table className="w-full text-sm table-fixed">
                  <colgroup>
                    {/* Store: narrower fixed width */}
                    <col style={{ width: '120px' }} />
                    {/* Product: flexible */}
                    <col />
                    {/* Price */}
                    <col style={{ width: '68px' }} />
                    {/* Level I / II / III: equal width */}
                    <col style={{ width: '100px' }} />
                    <col style={{ width: '100px' }} />
                    <col style={{ width: '100px' }} />
                    {/* Actions */}
                    <col style={{ width: '148px' }} />
                  </colgroup>
                  <thead>
                    <tr className="border-b border-theme-light-gray text-left text-theme-mid">
                      <th className="py-2 pr-2">Store</th>
                      <th className="py-2 pr-3">Product</th>
                      <th className="py-2 pr-2 text-right">Price</th>
                      <th className="py-2 pr-2">Level I</th>
                      <th className="py-2 pr-2">Level II</th>
                      <th className="py-2 pr-2">Level III</th>
                      <th className="py-2" />
                    </tr>
                  </thead>
                  <tbody>
                    {byDate[date].map((it) => {
                      const id = it.record_item_id
                      const isIdk = it.user_marked_idk === true
                      const l1Id = editL1[id] ?? ''
                      const l2Id = editL2[id] ?? ''
                      const l3Id = editL3[id] ?? ''
                      const L2List = getL2(l1Id)
                      const L3List = getL3(l2Id)
                      const saving = savingId === id
                      return (
                        <tr key={id} className="border-b border-theme-light-gray/50 hover:bg-theme-cream/30">
                          <td className="py-2 pr-2 align-top">
                            <StoreCell name={it.store_display_name} address={it.store_address} />
                          </td>
                          <td className="py-2 pr-3 text-theme-dark align-top">{it.product_name || '—'}</td>
                          <td className="py-2 pr-2 text-right tabular-nums align-top">{formatDollars(it.line_total_cents)}</td>
                          <td className="py-2 pr-2 align-top">
                            <select
                              className="border rounded px-1 py-0.5 text-xs w-full"
                              value={l1Id}
                              onChange={(e) => {
                                setEditL1((o) => ({ ...o, [id]: e.target.value }))
                                setEditL2((o) => ({ ...o, [id]: '' }))
                                setEditL3((o) => ({ ...o, [id]: '' }))
                              }}
                              disabled={isIdk}
                            >
                              <option value="">—</option>
                              {L1List.map((c) => (
                                <option key={c.id} value={c.id}>{c.name}</option>
                              ))}
                            </select>
                          </td>
                          <td className="py-2 pr-2 align-top">
                            <select
                              className="border rounded px-1 py-0.5 text-xs w-full"
                              value={l2Id}
                              onChange={(e) => {
                                setEditL2((o) => ({ ...o, [id]: e.target.value }))
                                setEditL3((o) => ({ ...o, [id]: '' }))
                              }}
                              disabled={isIdk}
                            >
                              <option value="">—</option>
                              {L2List.map((c) => (
                                <option key={c.id} value={c.id}>{c.name}</option>
                              ))}
                            </select>
                          </td>
                          <td className="py-2 pr-2 align-top">
                            <select
                              className="border rounded px-1 py-0.5 text-xs w-full"
                              value={l3Id}
                              onChange={(e) => setEditL3((o) => ({ ...o, [id]: e.target.value }))}
                              disabled={isIdk}
                            >
                              <option value="">—</option>
                              {L3List.map((c) => (
                                <option key={c.id} value={c.id}>{c.name}</option>
                              ))}
                            </select>
                          </td>
                          <td className="py-2 align-top">
                            {isIdk ? (
                              <span className="text-xs text-theme-mid">I don&apos;t know</span>
                            ) : (
                              <div className="flex flex-col gap-1">
                                <div className="flex items-center gap-1">
                                  <button
                                    type="button"
                                    disabled={saving || (!editL3[id] && !editL2[id] && !editL1[id])}
                                    onClick={() => confirmCategory(it)}
                                    className="text-xs px-2 py-1 rounded bg-green-100 text-green-800 hover:bg-green-200 disabled:opacity-50"
                                  >
                                    {saving ? '…' : 'Confirm'}
                                  </button>
                                  <button
                                    type="button"
                                    disabled={saving}
                                    onClick={() => openDismissModal(it)}
                                    className="text-xs px-2 py-1 rounded bg-theme-red/10 text-theme-red border border-theme-red/30 hover:bg-theme-red/15 disabled:opacity-50"
                                  >
                                    Delete
                                  </button>
                                </div>
                                <button
                                  type="button"
                                  disabled={saving}
                                  onClick={() => markIdk(it)}
                                  className="text-xs px-2 py-1 rounded border border-theme-mid text-theme-dark/90 hover:bg-theme-light-gray w-fit"
                                >
                                  I don&apos;t know
                                </button>
                              </div>
                            )}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Delete / Dismiss Modal */}
      {dismissModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-md mx-4 p-6">
            <h3 className="text-base font-semibold text-theme-dark mb-1">Delete item</h3>
            <p className="text-xs text-theme-mid mb-4">
              What happened with &ldquo;{dismissModal.item.product_name || 'this item'}&rdquo;? Please select a reason to continue.
            </p>

            <div className="space-y-3 mb-4">
              <label className="flex items-start gap-3 cursor-pointer">
                <input
                  type="radio"
                  name="dismiss-reason"
                  value="incorrect_item"
                  checked={dismissModal.reason === 'incorrect_item'}
                  onChange={() => setDismissModal((m) => m ? { ...m, reason: 'incorrect_item', comment: '' } : m)}
                  className="mt-0.5 shrink-0"
                />
                <div>
                  <span className="text-sm text-theme-dark font-medium">This is an incorrect item</span>
                  <p className="text-xs text-theme-mid mt-0.5">The item was extracted incorrectly by the system (e.g. phantom line, $0.00 unknown item).</p>
                </div>
              </label>

              <label className="flex items-start gap-3 cursor-pointer">
                <input
                  type="radio"
                  name="dismiss-reason"
                  value="other"
                  checked={dismissModal.reason === 'other'}
                  onChange={() => {
                    setDismissModal((m) => m ? { ...m, reason: 'other' } : m)
                    setTimeout(() => commentRef.current?.focus(), 50)
                  }}
                  className="mt-0.5 shrink-0"
                />
                <div className="flex-1">
                  <span className="text-sm text-theme-dark font-medium">Other</span>
                  <p className="text-xs text-theme-mid mt-0.5">Describe the issue — this will be escalated for review.</p>
                  {dismissModal.reason === 'other' && (
                    <textarea
                      ref={commentRef}
                      value={dismissModal.comment}
                      onChange={(e) => setDismissModal((m) => m ? { ...m, comment: e.target.value } : m)}
                      placeholder="Describe what's wrong with this item…"
                      rows={3}
                      className="mt-2 w-full border rounded px-2 py-1.5 text-xs resize-none focus:outline-none focus:ring-1 focus:ring-theme-mid"
                    />
                  )}
                </div>
              </label>
            </div>

            {dismissModal.error && (
              <p className="text-xs text-theme-red mb-3">{dismissModal.error}</p>
            )}

            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setDismissModal(null)}
                disabled={dismissModal.submitting}
                className="text-sm px-4 py-1.5 rounded border border-theme-mid text-theme-dark/90 hover:bg-theme-light-gray disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={submitDismiss}
                disabled={
                  dismissModal.submitting ||
                  !dismissModal.reason ||
                  (dismissModal.reason === 'other' && !dismissModal.comment.trim())
                }
                className="text-sm px-4 py-1.5 rounded bg-theme-red text-white hover:bg-theme-red/90 disabled:opacity-50"
              >
                {dismissModal.submitting ? 'Deleting…' : 'Delete'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
