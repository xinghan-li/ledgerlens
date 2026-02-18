'use client'

import { useEffect, useState } from 'react'
import { createClient } from '@/lib/supabase'

const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

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

  useEffect(() => {
    const supabase = createClient()
    supabase.auth.getSession().then(({ data: { session } }) => {
      setToken(session?.access_token ?? null)
    })
  }, [])

  const fetchList = async () => {
    if (!token) return
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams({ limit: String(limit), offset: String(offset) })
      if (statusFilter) params.set('status', statusFilter)
      const res = await fetch(`${apiUrl}/api/admin/store-review?${params}`, {
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

  const fetchChains = async () => {
    if (!token) return
    try {
      const res = await fetch(`${apiUrl}/api/admin/store-review/chains?active_only=false`, {
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
      const res = await fetch(`${apiUrl}/api/admin/store-review/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify(payload),
      })
      if (!res.ok) throw new Error(await res.text())
      fetchList()
    } catch (e) {
      setError(e instanceof Error ? e.message : '更新失败')
    }
  }

  const getCurrentRawName = (r: Row) => editedRawName[r.id] ?? r.raw_name ?? ''
  const getCurrentNormalizedName = (r: Row) =>
    (editedNormalizedName[r.id] ?? r.normalized_name ?? '').trim() || (r.raw_name ?? '').toLowerCase().replace(/\s+/g, '_')
  const getCurrentLocationName = (r: Row) => (editedLocationName[r.id] ?? r.raw_name ?? '').trim() || 'Store'

  const handleApprove = async (id: string) => {
    if (!token) return
    const row = rows.find((x) => x.id === id)
    if (!row || row.status !== 'pending') return
    setApprovingId(id)
    setError(null)
    try {
      const chainName = getCurrentRawName(row).trim()
      const asNewChain = approveAsNewChain[id] !== false
      const addAsLocationOfChainId = asNewChain ? undefined : (selectedChainId[id] || undefined)
      if (!asNewChain && !addAsLocationOfChainId) {
        throw new Error('请选择“新建 chain”或“归入已有 chain”')
      }
      if (asNewChain && !chainName) throw new Error('新建 chain 时请填写 chain 名称')
      const patchPayload: Record<string, unknown> = {}
      if (chainName !== (row.raw_name ?? '')) patchPayload.raw_name = chainName
      if (Object.keys(patchPayload).length > 0) {
        const patchRes = await fetch(`${apiUrl}/api/admin/store-review/${id}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
          body: JSON.stringify(patchPayload),
        })
        if (!patchRes.ok) throw new Error(await patchRes.text())
      }
      const meta = (row.metadata as { address?: Record<string, string> })?.address ?? {}
      const body: Record<string, unknown> = {
        chain_name: asNewChain ? chainName : undefined,
        add_as_location_of_chain_id: addAsLocationOfChainId || undefined,
        location_name: getCurrentLocationName(row),
      }
      const addr = editedAddress[id] ?? row.address_display ?? ''
      if (addr) {
        const parts = addr.split(',').map((s) => s.trim())
        if (parts[0]) body.address_line1 = parts[0]
        if (parts[1]) body.city = parts[1]
        if (parts[2]) body.state = parts[2]
        if (parts[3]) body.zip_code = parts[3]
        if (parts[4]) body.country_code = parts[4]
      } else if (meta.address1) {
        body.address_line1 = meta.address1
        if (meta.city) body.city = meta.city
        if (meta.state) body.state = meta.state
        if (meta.zipcode) body.zip_code = meta.zipcode
        if (meta.country) body.country_code = meta.country
      }
      const res = await fetch(`${apiUrl}/api/admin/store-review/${id}/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify(body),
      })
      const data = res.ok ? await res.json().catch(() => ({})) : await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.detail || 'Approve 失败')
      setEditedRawName((p) => { const n = { ...p }; delete n[id]; return n })
      setEditedNormalizedName((p) => { const n = { ...p }; delete n[id]; return n })
      setApproveAsNewChain((p) => { const n = { ...p }; delete n[id]; return n })
      setSelectedChainId((p) => { const n = { ...p }; delete n[id]; return n })
      setEditedLocationName((p) => { const n = { ...p }; delete n[id]; return n })
      setEditedAddress((p) => { const n = { ...p }; delete n[id]; return n })
      fetchList()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Approve 失败')
    } finally {
      setApprovingId(null)
    }
  }

  const handleReject = async (id: string) => {
    if (!token) return
    setRejectingId(id)
    setError(null)
    try {
      const res = await fetch(`${apiUrl}/api/admin/store-review/${id}/reject`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ rejection_reason: rejectReason || undefined }),
      })
      if (!res.ok) throw new Error(await res.text())
      setRejectReason('')
      setRejectingId(null)
      fetchList()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Reject 失败')
    } finally {
      setRejectingId(null)
    }
  }

  const openReject = (id: string) => {
    setRejectingId(id)
    setRejectReason('')
  }

  if (!token) {
    return <div className="text-center py-8 text-gray-500">请先登录</div>
  }

  return (
    <div>
      <h2 className="text-lg font-semibold mb-4">门店审核 (Store Review)</h2>
      <div className="mb-4 flex gap-4 items-center flex-wrap">
        <label className="flex items-center gap-2">
          状态：
          <select
            value={statusFilter}
            onChange={(e) => { setStatusFilter(e.target.value); setOffset(0) }}
            className="border rounded px-2 py-1"
          >
            <option value="">全部</option>
            <option value="pending">pending</option>
            <option value="approved">approved</option>
            <option value="rejected">rejected</option>
          </select>
        </label>
        <span className="text-sm text-gray-500">共 {total} 条</span>
      </div>
      {error && <div className="mb-4 p-2 bg-red-100 text-red-700 rounded text-sm">{error}</div>}
      {loading ? (
        <p className="text-gray-500">加载中...</p>
      ) : (
        <div className="overflow-x-auto bg-white rounded-lg shadow">
          <table className="min-w-full divide-y divide-gray-200 text-sm">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-3 py-2 text-left">raw_name</th>
                <th className="px-3 py-2 text-left">normalized_name</th>
                <th className="px-3 py-2 text-left">suggested_chain</th>
                <th className="px-3 py-2 text-left">address</th>
                <th className="px-3 py-2 text-left">source</th>
                <th className="px-3 py-2 text-left">status</th>
                <th className="px-3 py-2 text-left">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {rows.map((r) => (
                <tr key={r.id}>
                  <td className="px-3 py-2">
                    <input
                      className="border rounded px-1 w-36"
                      value={editedRawName[r.id] ?? r.raw_name ?? ''}
                      onChange={(e) => setEditedRawName((p) => ({ ...p, [r.id]: e.target.value }))}
                      readOnly={r.status !== 'pending'}
                    />
                  </td>
                  <td className="px-3 py-2">
                    <input
                      className="border rounded px-1 w-32"
                      value={editedNormalizedName[r.id] ?? r.normalized_name ?? ''}
                      onChange={(e) => setEditedNormalizedName((p) => ({ ...p, [r.id]: e.target.value }))}
                      readOnly={r.status !== 'pending'}
                    />
                  </td>
                  <td className="px-3 py-2 text-gray-600">{r.suggested_chain_name ?? '—'}</td>
                  <td className="px-3 py-2 max-w-[200px]">
                    {r.status === 'pending' ? (
                      <input
                        className="border rounded px-1 w-full"
                        placeholder="地址（可选）"
                        value={editedAddress[r.id] ?? r.address_display ?? ''}
                        onChange={(e) => setEditedAddress((p) => ({ ...p, [r.id]: e.target.value }))}
                      />
                    ) : (
                      <span className="text-gray-600 truncate block">{r.address_display ?? '—'}</span>
                    )}
                  </td>
                  <td className="px-3 py-2">{r.source}</td>
                  <td className="px-3 py-2">
                    <select
                      className="border rounded px-1"
                      value={r.status}
                      onChange={(e) => handlePatch(r.id, { status: e.target.value })}
                    >
                      <option value="pending">pending</option>
                      <option value="approved">approved</option>
                      <option value="rejected">rejected</option>
                    </select>
                  </td>
                  <td className="px-3 py-2">
                    {r.status === 'pending' && (
                      <>
                        <div className="flex flex-col gap-1 mb-1">
                          <label className="flex items-center gap-1">
                            <input
                              type="radio"
                              checked={approveAsNewChain[r.id] !== false}
                              onChange={() => setApproveAsNewChain((p) => ({ ...p, [r.id]: true }))}
                            />
                            新建 chain
                          </label>
                          <label className="flex items-center gap-1">
                            <input
                              type="radio"
                              checked={approveAsNewChain[r.id] === false}
                              onChange={() => setApproveAsNewChain((p) => ({ ...p, [r.id]: false }))}
                            />
                            归入已有 chain
                          </label>
                        </div>
                        {approveAsNewChain[r.id] === false && (
                          <select
                            className="border rounded px-1 w-40 mb-1"
                            value={selectedChainId[r.id] ?? ''}
                            onChange={(e) => setSelectedChainId((p) => ({ ...p, [r.id]: e.target.value }))}
                          >
                            <option value="">选择 chain</option>
                            {chains.map((c) => (
                              <option key={c.id} value={c.id}>{c.name}</option>
                            ))}
                          </select>
                        )}
                        <input
                          className="border rounded px-1 w-32 mb-1 block"
                          placeholder="门店名称"
                          value={editedLocationName[r.id] ?? r.raw_name ?? ''}
                          onChange={(e) => setEditedLocationName((p) => ({ ...p, [r.id]: e.target.value }))}
                        />
                        <div className="flex gap-1">
                          <button
                            className="px-2 py-1 bg-green-100 rounded text-green-800 disabled:opacity-50"
                            disabled={approvingId !== null}
                            onClick={() => handleApprove(r.id)}
                          >
                            {approvingId === r.id ? '...' : 'Approve'}
                          </button>
                          <button
                            className="px-2 py-1 bg-red-50 rounded text-red-700 border border-red-200"
                            onClick={() => openReject(r.id)}
                          >
                            Reject
                          </button>
                        </div>
                      </>
                    )}
                    {(r.status === 'approved' || r.status === 'rejected') && (
                      <button
                        className="px-2 py-1 border rounded text-gray-600"
                        onClick={() => handlePatch(r.id, { status: 'pending' })}
                      >
                        重开
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
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

      {rejectingId && (
        <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-10">
          <div className="bg-white rounded-lg p-4 shadow max-w-md w-full mx-4">
            <p className="font-medium mb-2">拒绝原因（可选）</p>
            <input
              className="border rounded px-2 py-1 w-full mb-4"
              value={rejectReason}
              onChange={(e) => setRejectReason(e.target.value)}
              placeholder="rejection_reason"
            />
            <div className="flex gap-2">
              <button className="px-3 py-1 bg-red-100 rounded text-red-800" onClick={() => handleReject(rejectingId)}>
                确认拒绝
              </button>
              <button className="px-3 py-1 border rounded" onClick={() => setRejectingId(null)}>
                取消
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
