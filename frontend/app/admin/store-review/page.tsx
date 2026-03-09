'use client'

import { Fragment, useEffect, useState } from 'react'
import { getFirebaseAuth } from '@/lib/firebase'
import { onAuthStateChanged } from 'firebase/auth'
import { useApiUrl } from '@/lib/api-url-context'

type Row = {
  id: string
  raw_name: string
  normalized_name: string
  source: string
  receipt_id: string | null
  suggested_chain_id: string | null
  suggested_chain_name?: string | null
  suggested_location_id: string | null
  confidence_score: number | null
  status: string
  rejection_reason: string | null
  metadata: Record<string, unknown> | null
  address_display?: string | null
  created_at: string
  reviewed_at: string | null
  reviewed_by: string | null
}

type Chain = { id: string; name: string; normalized_name: string }

export default function StoreReviewPage() {
  const apiBaseUrl = useApiUrl()
  const [rows, setRows] = useState<Row[]>([])
  const [total, setTotal] = useState(0)
  const [statusFilter, setStatusFilter] = useState('pending')
  const [limit] = useState(50)
  const [offset, setOffset] = useState(0)
  const [loading, setLoading] = useState(true)
  const [token, setToken] = useState<string | null>(null)
  const [chains, setChains] = useState<Chain[]>([])
  const [error, setError] = useState<string | null>(null)
  const [approvingId, setApprovingId] = useState<string | null>(null)
  const [rejectingId, setRejectingId] = useState<string | null>(null)
  const [rejectReason, setRejectReason] = useState('')
  const [editedRawName, setEditedRawName] = useState<Record<string, string>>({})
  const [editedNormalizedName, setEditedNormalizedName] = useState<Record<string, string>>({})
  const [approveAsNewChain, setApproveAsNewChain] = useState<Record<string, boolean>>({})
  const [selectedChainId, setSelectedChainId] = useState<Record<string, string>>({})
  const [editedLocationName, setEditedLocationName] = useState<Record<string, string>>({})
  const [editedAddress, setEditedAddress] = useState<Record<string, string>>({})
  const [expandedId, setExpandedId] = useState<string | null>(null)
  // store_locations-style prefilled fields (for expanded card)
  const [cardAddressLine1, setCardAddressLine1] = useState<Record<string, string>>({})
  const [cardAddressLine2, setCardAddressLine2] = useState<Record<string, string>>({})
  const [cardCity, setCardCity] = useState<Record<string, string>>({})
  const [cardState, setCardState] = useState<Record<string, string>>({})
  const [cardZipCode, setCardZipCode] = useState<Record<string, string>>({})
  const [cardCountryCode, setCardCountryCode] = useState<Record<string, string>>({})
  const [cardPhone, setCardPhone] = useState<Record<string, string>>({})
  const [backfilling, setBackfilling] = useState(false)
  const [backfillResult, setBackfillResult] = useState<{ total_updated: number; per_location: { location_id: string; updated: number }[] } | null>(null)

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
      if (statusFilter) params.set('status', statusFilter)
      const res = await fetch(`${apiBaseUrl}/api/admin/store-review?${params}`, {
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

  const fetchChains = async () => {
    if (!token) return
    try {
      const res = await fetch(`${apiBaseUrl}/api/admin/store-review/chains?active_only=false`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (res.ok) {
        const data = await res.json()
        setChains(data.data || [])
      }
    } catch (_) {}
  }

  useEffect(() => {
    if (token) {
      fetchList()
      fetchChains()
    }
  }, [token, statusFilter, offset])

  const handlePatch = async (id: string, payload: Record<string, unknown>) => {
    if (!token) return
    try {
      const res = await fetch(`${apiBaseUrl}/api/admin/store-review/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify(payload),
      })
      if (!res.ok) throw new Error(await res.text())
      fetchList()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Update failed')
    }
  }

  const getCurrentRawName = (r: Row) => editedRawName[r.id] ?? r.raw_name ?? ''
  const getCurrentNormalizedName = (r: Row) =>
    (editedNormalizedName[r.id] ?? r.normalized_name ?? '').trim() || (r.raw_name ?? '').toLowerCase().replace(/\s+/g, '_')
  const getCurrentLocationName = (r: Row) => (editedLocationName[r.id] ?? r.raw_name ?? '').trim() || 'Store'

  const getMetaAddress = (r: Row) => (r.metadata as { address?: Record<string, string> })?.address ?? {}
  const getCardAddr = (r: Row) => {
    const meta = getMetaAddress(r)
    return {
      address_line1: cardAddressLine1[r.id] ?? meta.address_line1 ?? meta.address1 ?? '',
      address_line2: cardAddressLine2[r.id] ?? meta.address_line2 ?? meta.address2 ?? '',
      city: cardCity[r.id] ?? meta.city ?? '',
      state: cardState[r.id] ?? meta.state ?? '',
      zip_code: cardZipCode[r.id] ?? meta.zip_code ?? meta.zipcode ?? '',
      country_code: cardCountryCode[r.id] ?? meta.country ?? '',
      phone: cardPhone[r.id] ?? (meta as { phone?: string }).phone ?? '',
    }
  }
  const formatAddressLine = (r: Row) => {
    const a = getCardAddr(r)
    const addressPart = a.address_line2 && a.address_line1
      ? `${a.address_line2} - ${a.address_line1}`
      : a.address_line2 || a.address_line1
    const stateZipPart = a.state && a.zip_code ? `${a.state} ${a.zip_code}` : a.state || a.zip_code
    const parts = [addressPart, a.city, stateZipPart, a.country_code].filter(Boolean)
    return parts.length ? parts.join(', ') : (getMetaAddress(r).full_address as string) ?? '—'
  }

  const handleApprove = async (id: string) => {
    if (!token) return
    const row = rows.find((x) => x.id === id)
    if (!row || row.status !== 'pending') return
    setApprovingId(id)
    setError(null)
    try {
      const chainName = getCurrentRawName(row).trim()
      const asNewChain = approveAsNewChain[id] !== false
      const addAsLocationOfChainId = asNewChain ? undefined : (selectedChainId[id] || row.suggested_chain_id || undefined)
      if (!asNewChain && !addAsLocationOfChainId) {
        throw new Error('Please choose "Create new chain" or "Assign to existing chain"')
      }
      if (asNewChain && !chainName) throw new Error('Please enter a chain name when creating a new chain')
      const patchPayload: Record<string, unknown> = {}
      if (chainName !== (row.raw_name ?? '')) patchPayload.raw_name = chainName
      if (Object.keys(patchPayload).length > 0) {
        const patchRes = await fetch(`${apiBaseUrl}/api/admin/store-review/${id}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
          body: JSON.stringify(patchPayload),
        })
        if (!patchRes.ok) throw new Error(await patchRes.text())
      }
      const cardAddr = getCardAddr(row)
      const body: Record<string, unknown> = {
        chain_name: asNewChain ? chainName : undefined,
        add_as_location_of_chain_id: addAsLocationOfChainId || undefined,
        location_name: getCurrentLocationName(row),
      }
      if (cardAddr.address_line1) body.address_line1 = cardAddr.address_line1
      if (cardAddr.address_line2) body.address_line2 = cardAddr.address_line2
      if (cardAddr.city) body.city = cardAddr.city
      if (cardAddr.state) body.state = cardAddr.state
      if (cardAddr.zip_code) body.zip_code = cardAddr.zip_code
      if (cardAddr.country_code) body.country_code = cardAddr.country_code
      if (cardAddr.phone) body.phone = cardAddr.phone
      const res = await fetch(`${apiBaseUrl}/api/admin/store-review/${id}/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify(body),
      })
      const data = res.ok ? await res.json().catch(() => ({})) : await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.detail || 'Approve failed')
      setEditedRawName((p) => { const n = { ...p }; delete n[id]; return n })
      setEditedNormalizedName((p) => { const n = { ...p }; delete n[id]; return n })
      setApproveAsNewChain((p) => { const n = { ...p }; delete n[id]; return n })
      setSelectedChainId((p) => { const n = { ...p }; delete n[id]; return n })
      setEditedLocationName((p) => { const n = { ...p }; delete n[id]; return n })
      setCardAddressLine1((p) => { const n = { ...p }; delete n[id]; return n })
      setCardAddressLine2((p) => { const n = { ...p }; delete n[id]; return n })
      setCardCity((p) => { const n = { ...p }; delete n[id]; return n })
      setCardState((p) => { const n = { ...p }; delete n[id]; return n })
      setCardZipCode((p) => { const n = { ...p }; delete n[id]; return n })
      setCardCountryCode((p) => { const n = { ...p }; delete n[id]; return n })
      setCardPhone((p) => { const n = { ...p }; delete n[id]; return n })
      setExpandedId(null)
      fetchList()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Approve failed')
    } finally {
      setApprovingId(null)
    }
  }

  const handleReject = async (id: string) => {
    if (!token) return
    setRejectingId(id)
    setError(null)
    try {
      const res = await fetch(`${apiBaseUrl}/api/admin/store-review/${id}/reject`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ rejection_reason: rejectReason || undefined }),
      })
      if (!res.ok) throw new Error(await res.text())
      setRejectReason('')
      setRejectingId(null)
      fetchList()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Reject failed')
    } finally {
      setRejectingId(null)
    }
  }

  const openReject = (id: string) => {
    setRejectingId(id)
    setRejectReason('')
  }

  const handleBackfillStoreLocations = async () => {
    if (!token) return
    setBackfilling(true)
    setBackfillResult(null)
    setError(null)
    try {
      const res = await fetch(`${apiBaseUrl}/api/admin/store-review/backfill-store-locations`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({}),
      })
      if (!res.ok) throw new Error(await res.text())
      const data = await res.json()
      setBackfillResult({ total_updated: data.total_updated ?? 0, per_location: data.per_location ?? [] })
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Backfill failed')
    } finally {
      setBackfilling(false)
    }
  }

  if (!token) {
    return <div className="text-center py-8 text-theme-mid">Please sign in first.</div>
  }

  return (
    <div>
      <h2 className="text-lg font-semibold mb-4">Store Review</h2>
      <div className="mb-4 flex gap-4 items-center flex-wrap">
        <label className="flex items-center gap-2">
          Status:
          <select
            value={statusFilter}
            onChange={(e) => { setStatusFilter(e.target.value); setOffset(0) }}
            className="border rounded px-2 py-1"
          >
            <option value="">All</option>
            <option value="pending">pending</option>
            <option value="approved">approved</option>
            <option value="rejected">rejected</option>
          </select>
        </label>
        <span className="text-sm text-theme-mid">{total} total</span>
        <button
          type="button"
          onClick={handleBackfillStoreLocations}
          disabled={backfilling}
          className="px-3 py-1.5 rounded border border-theme-mid/40 bg-theme-cream/60 hover:bg-theme-cream disabled:opacity-50 text-sm"
        >
          {backfilling ? 'Backfilling…' : 'Backfill record_summaries store_location_id'}
        </button>
        {backfillResult && (
          <span className="text-sm text-theme-mid">
            Updated {backfillResult.total_updated} receipt(s) across {backfillResult.per_location.filter((p) => p.updated > 0).length} location(s).
          </span>
        )}
      </div>
      {error && <div className="mb-4 p-2 bg-theme-red/15 text-theme-red rounded text-sm">{error}</div>}
      {loading ? (
        <p className="text-theme-mid">Loading…</p>
      ) : (
        <div className="overflow-x-auto bg-white rounded-lg shadow">
          <table className="min-w-full divide-y divide-theme-light-gray text-sm">
            <thead className="bg-theme-cream/80">
              <tr>
                <th className="px-3 py-2 text-left">raw_name</th>
                <th className="px-3 py-2 text-left">normalized_name</th>
                <th className="px-3 py-2 text-left">suggested_chain</th>
                <th className="px-3 py-2 text-left">address</th>
                <th className="px-3 py-2 text-left">source</th>
                <th className="px-3 py-2 text-left">status</th>
                <th className="px-3 py-2 text-left">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-theme-light-gray">
              {rows.map((r) => (
                <Fragment key={r.id}>
                  <tr
                    className={r.status === 'pending' ? 'cursor-pointer hover:bg-theme-cream/80' : ''}
                    onClick={() => {
                      if (r.status !== 'pending') return
                      const next = expandedId === r.id ? null : r.id
                      setExpandedId(next)
                      if (next === r.id && r.suggested_chain_id && selectedChainId[r.id] === undefined) {
                        setSelectedChainId((p) => ({ ...p, [r.id]: r.suggested_chain_id! }))
                        setApproveAsNewChain((p) => ({ ...p, [r.id]: false }))
                      }
                    }}
                  >
                    <td className="px-3 py-2">
                      <input
                        className="border rounded px-1 w-36"
                        value={editedRawName[r.id] ?? r.raw_name ?? ''}
                        onChange={(e) => { e.stopPropagation(); setEditedRawName((p) => ({ ...p, [r.id]: e.target.value }))}}
                        readOnly={r.status !== 'pending'}
                        onClick={(e) => e.stopPropagation()}
                      />
                    </td>
                    <td className="px-3 py-2">
                      <input
                        className="border rounded px-1 w-32"
                        value={editedNormalizedName[r.id] ?? r.normalized_name ?? ''}
                        onChange={(e) => { e.stopPropagation(); setEditedNormalizedName((p) => ({ ...p, [r.id]: e.target.value }))}}
                        readOnly={r.status !== 'pending'}
                        onClick={(e) => e.stopPropagation()}
                      />
                    </td>
                    <td className="px-3 py-2 text-theme-dark/90">{r.suggested_chain_name ?? '—'}</td>
                    <td className="px-3 py-2 max-w-[200px]">
                      <span className="text-theme-dark/90 truncate block">{r.address_display ?? '—'}</span>
                    </td>
                    <td className="px-3 py-2">{r.source}</td>
                    <td className="px-3 py-2">
                      <select
                        className="border rounded px-1"
                        value={r.status}
                        onChange={(e) => { e.stopPropagation(); handlePatch(r.id, { status: e.target.value })}}
                        onClick={(e) => e.stopPropagation()}
                      >
                        <option value="pending">pending</option>
                        <option value="approved">approved</option>
                        <option value="rejected">rejected</option>
                      </select>
                    </td>
                    <td className="px-3 py-2" onClick={(e) => e.stopPropagation()}>
                      {r.status === 'pending' && (
                        <button
                          type="button"
                          className="p-1 rounded hover:bg-theme-light-gray"
                          aria-label={expandedId === r.id ? 'Collapse' : 'Expand'}
                          onClick={() => {
                            const next = expandedId === r.id ? null : r.id
                            setExpandedId(next)
                            if (next === r.id && r.suggested_chain_id && selectedChainId[r.id] === undefined) {
                              setSelectedChainId((p) => ({ ...p, [r.id]: r.suggested_chain_id! }))
                              setApproveAsNewChain((p) => ({ ...p, [r.id]: false }))
                            }
                          }}
                        >
                          {expandedId === r.id ? '▼' : '▶'}
                        </button>
                      )}
                      {(r.status === 'approved' || r.status === 'rejected') && (
                        <button
                          className="px-2 py-1 border rounded text-theme-dark/90"
                          onClick={() => handlePatch(r.id, { status: 'pending' })}
                        >
                          Reopen
                        </button>
                      )}
                    </td>
                  </tr>
                  {expandedId === r.id && r.status === 'pending' && (
                    <tr>
                      <td colSpan={7} className="px-0 py-0 bg-theme-cream/80">
                        <div className="p-4 border-t border-b border-theme-light-gray">
                          <p className="text-sm font-medium text-theme-dark/90 mb-3">Pre-filled store_chains / store_locations — confirm then Approve.</p>
                          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
                            <div className="space-y-2">
                              <p className="text-xs font-medium text-theme-mid">store_chains (when creating new chain)</p>
                              <div className="p-3 bg-white rounded border space-y-2 mb-2">
                                <span className="text-xs font-medium text-theme-mid">Action</span>
                                <div className="flex flex-col gap-2">
                                  <label className="flex items-center gap-1">
                                    <input
                                      type="radio"
                                      checked={approveAsNewChain[r.id] !== false}
                                      onChange={() => setApproveAsNewChain((p) => ({ ...p, [r.id]: true }))}
                                    />
                                    Create new chain
                                  </label>
                                  <label className="flex items-center gap-1">
                                    <input
                                      type="radio"
                                      checked={approveAsNewChain[r.id] === false}
                                      onChange={() => setApproveAsNewChain((p) => ({ ...p, [r.id]: false }))}
                                    />
                                    Assign to existing chain
                                  </label>
                                  {approveAsNewChain[r.id] === false && (
                                    <select
                                      className="border rounded px-2 py-1 w-full max-w-xs"
                                      value={selectedChainId[r.id] ?? r.suggested_chain_id ?? ''}
                                      onChange={(e) => setSelectedChainId((p) => ({ ...p, [r.id]: e.target.value }))}
                                    >
                                      <option value="">Select chain</option>
                                      {chains.map((c) => (
                                        <option key={c.id} value={c.id}>{c.name}</option>
                                      ))}
                                    </select>
                                  )}
                                  {r.suggested_chain_id != null && (
                                    <span className="text-xs text-theme-mid">
                                      AI suggestion: {r.suggested_chain_name ?? r.suggested_chain_id}
                                      {r.confidence_score != null && ` (${(r.confidence_score * 100).toFixed(0)}%)`}
                                    </span>
                                  )}
                                </div>
                              </div>
                              <div>
                                <label className="block text-xs text-theme-mid">name</label>
                                <input
                                  className={`border rounded px-2 py-1 w-full ${approveAsNewChain[r.id] === false ? 'bg-theme-light-gray/50 text-theme-mid cursor-not-allowed' : ''}`}
                                  value={editedRawName[r.id] ?? r.raw_name ?? ''}
                                  onChange={(e) => setEditedRawName((p) => ({ ...p, [r.id]: e.target.value }))}
                                  readOnly={approveAsNewChain[r.id] === false}
                                  disabled={approveAsNewChain[r.id] === false}
                                />
                              </div>
                              <div>
                                <label className="block text-xs text-theme-mid">normalized_name</label>
                                <input
                                  className={`border rounded px-2 py-1 w-full ${approveAsNewChain[r.id] === false ? 'bg-theme-light-gray/50 text-theme-mid cursor-not-allowed' : ''}`}
                                  value={editedNormalizedName[r.id] ?? r.normalized_name ?? ''}
                                  onChange={(e) => setEditedNormalizedName((p) => ({ ...p, [r.id]: e.target.value }))}
                                  readOnly={approveAsNewChain[r.id] === false}
                                  disabled={approveAsNewChain[r.id] === false}
                                />
                              </div>
                            </div>
                            <div className="space-y-2">
                              <p className="text-xs font-medium text-theme-mid">store_locations</p>
                              <p className="text-xs text-theme-dark/80">
                                Address preview: <span className="font-mono text-theme-dark">{formatAddressLine(r)}</span>
                              </p>
                              <div>
                                <label className="block text-xs text-theme-mid">Store name (name)</label>
                                <input
                                  className="border rounded px-2 py-1 w-full"
                                  placeholder="Store name"
                                  value={editedLocationName[r.id] ?? r.raw_name ?? ''}
                                  onChange={(e) => setEditedLocationName((p) => ({ ...p, [r.id]: e.target.value }))}
                                />
                              </div>
                              <div>
                                <label className="block text-xs text-theme-mid">address_line1</label>
                                <input
                                  className="border rounded px-2 py-1 w-full"
                                  value={getCardAddr(r).address_line1}
                                  onChange={(e) => setCardAddressLine1((p) => ({ ...p, [r.id]: e.target.value }))}
                                />
                              </div>
                              <div>
                                <label className="block text-xs text-theme-mid">address_line2</label>
                                <input
                                  className="border rounded px-2 py-1 w-full"
                                  placeholder="Suite / Unit"
                                  value={getCardAddr(r).address_line2}
                                  onChange={(e) => setCardAddressLine2((p) => ({ ...p, [r.id]: e.target.value }))}
                                />
                              </div>
                              <div className="grid grid-cols-2 gap-2">
                                <div>
                                  <label className="block text-xs text-theme-mid">city</label>
                                  <input
                                    className="border rounded px-2 py-1 w-full"
                                    value={getCardAddr(r).city}
                                    onChange={(e) => setCardCity((p) => ({ ...p, [r.id]: e.target.value }))}
                                  />
                                </div>
                                <div>
                                  <label className="block text-xs text-theme-mid">state</label>
                                  <input
                                    className="border rounded px-2 py-1 w-full"
                                    value={getCardAddr(r).state}
                                    onChange={(e) => setCardState((p) => ({ ...p, [r.id]: e.target.value }))}
                                  />
                                </div>
                              </div>
                              <div className="grid grid-cols-2 gap-2">
                                <div>
                                  <label className="block text-xs text-theme-mid">zip_code</label>
                                  <input
                                    className="border rounded px-2 py-1 w-full"
                                    value={getCardAddr(r).zip_code}
                                    onChange={(e) => setCardZipCode((p) => ({ ...p, [r.id]: e.target.value }))}
                                  />
                                </div>
                                <div>
                                  <label className="block text-xs text-theme-mid">country_code</label>
                                  <input
                                    className="border rounded px-2 py-1 w-full"
                                    placeholder="US / CA"
                                    value={getCardAddr(r).country_code}
                                    onChange={(e) => setCardCountryCode((p) => ({ ...p, [r.id]: e.target.value }))}
                                  />
                                </div>
                              </div>
                              <div>
                                <label className="block text-xs text-theme-mid">Phone</label>
                                <input
                                  className="border rounded px-2 py-1 w-full"
                                  placeholder="xxx-xxx-xxxx"
                                  value={getCardAddr(r).phone}
                                  onChange={(e) => setCardPhone((p) => ({ ...p, [r.id]: e.target.value }))}
                                />
                              </div>
                            </div>
                          </div>
                          <div className="flex justify-end gap-2 pt-3 border-t">
                            <button
                              className="px-3 py-1.5 bg-green-100 rounded text-green-800 disabled:opacity-50"
                              disabled={approvingId !== null}
                              onClick={() => handleApprove(r.id)}
                            >
                              {approvingId === r.id ? '...' : 'Approve'}
                            </button>
                            <button
                              className="px-3 py-1.5 bg-theme-red/10 rounded text-theme-red border border-theme-red/30"
                              onClick={() => openReject(r.id)}
                            >
                              Reject
                            </button>
                          </div>
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
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

      {rejectingId && (
        <div className="fixed inset-0 bg-theme-black/30 flex items-center justify-center z-10">
          <div className="bg-white rounded-lg p-4 shadow max-w-md w-full mx-4">
            <p className="font-medium mb-2">Reject reason (optional)</p>
            <input
              className="border rounded px-2 py-1 w-full mb-4"
              value={rejectReason}
              onChange={(e) => setRejectReason(e.target.value)}
              placeholder="rejection_reason"
            />
            <div className="flex gap-2">
              <button className="px-3 py-1 bg-theme-red/15 rounded text-theme-red" onClick={() => handleReject(rejectingId)}>
                Confirm reject
              </button>
              <button className="px-3 py-1 border rounded" onClick={() => setRejectingId(null)}>
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
