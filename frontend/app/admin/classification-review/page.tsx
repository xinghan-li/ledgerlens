'use client'

import { useEffect, useState } from 'react'
import { getFirebaseAuth } from '@/lib/firebase'
import { onAuthStateChanged } from 'firebase/auth'

const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

function prefillNormalizedName(raw: string): string {
  return (raw ?? '').toLowerCase().replace(/\s+/g, '_')
}

type Cat = { id: string; name: string; path: string; level: number; parent_id: string | null }

function CategoryCascade({
  row,
  level1,
  level2,
  level3,
  getAncestorIds,
  editedL1,
  editedL2,
  editedCategoryId,
  onEditedL1,
  onEditedL2,
  onEditedCategoryId,
  disabled,
}: {
  row: Row
  level1: Cat[]
  level2: Cat[]
  level3: Cat[]
  getAncestorIds: (cid: string | null) => { l1: string | null; l2: string | null }
  editedL1: Record<string, string>
  editedL2: Record<string, string>
  editedCategoryId: Record<string, string>
  onEditedL1: (id: string, val: string) => void
  onEditedL2: (id: string, val: string) => void
  onEditedCategoryId: (id: string, val: string) => void
  disabled?: boolean
}) {
  const effectiveCategoryId = editedCategoryId[row.id] ?? row.category_id ?? ''
  const { l1: derivedL1, l2: derivedL2 } = getAncestorIds(effectiveCategoryId || null)
  const l1Id = (derivedL1 ?? editedL1[row.id] ?? '')
  const l2Id = (derivedL2 ?? editedL2[row.id] ?? '')
  const l2Options = level2.filter((c) => c.parent_id === l1Id)
  let l3Options = level3.filter((c) => c.parent_id === l2Id)
  if (effectiveCategoryId && !l3Options.some((c) => c.id === effectiveCategoryId)) {
    const sel = level3.find((c) => c.id === effectiveCategoryId)
    if (sel) l3Options = [...l3Options, sel]
  }

  const l1Name = level1.find((c) => c.id === l1Id)?.name ?? '—'
  const l2Name = level2.find((c) => c.id === l2Id)?.name ?? '—'
  const l3Name = level3.find((c) => c.id === effectiveCategoryId)?.name ?? '—'

  if (disabled) {
    return (
      <>
        <td className="px-2 py-2 truncate" title={l1Name}>{l1Name}</td>
        <td className="px-2 py-2 truncate" title={l2Name}>{l2Name}</td>
        <td className="px-2 py-2 truncate" title={l3Name}>{l3Name}</td>
      </>
    )
  }

  return (
    <>
      <td className="px-2 py-2 overflow-hidden">
        <select
          className="border border-gray-200 rounded px-1 w-full max-w-[6.5rem] focus:ring-1 focus:ring-gray-300 focus:border-gray-300"
          value={l1Id}
          onChange={(e) => {
            const v = e.target.value || ''
            onEditedL1(row.id, v)
            onEditedL2(row.id, '')
            onEditedCategoryId(row.id, '')
          }}
        >
          <option value="">--</option>
          {level1.map((c) => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>
      </td>
      <td className="px-2 py-2 overflow-hidden">
        <select
          className="border border-gray-200 rounded px-1 w-full max-w-[6.5rem] focus:ring-1 focus:ring-gray-300 focus:border-gray-300"
          value={l2Id}
          onChange={(e) => {
            const v = e.target.value || ''
            onEditedL2(row.id, v)
            onEditedCategoryId(row.id, '')
          }}
        >
          <option value="">--</option>
          {l2Options.map((c) => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>
      </td>
      <td className="px-2 py-2 overflow-hidden">
        <select
          className="border border-gray-200 rounded px-1 w-full max-w-[6.5rem] focus:ring-1 focus:ring-gray-300 focus:border-gray-300"
          value={effectiveCategoryId}
          onChange={(e) => onEditedCategoryId(row.id, e.target.value || '')}
        >
          <option value="">--</option>
          {l3Options.map((c) => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>
      </td>
    </>
  )
}

type Row = {
  id: string
  raw_product_name: string
  normalized_name: string | null
  category_id: string | null
  category_name?: string | null
  category_path?: string | null
  store_chain_name?: string | null
  size_quantity: number | null
  size_unit: string | null
  package_type: string | null
  match_type: string
  status: string
  created_at: string
  confirmed_at?: string | null
  confirmed_by?: string | null
}

export default function ClassificationReviewPage() {
  const [rows, setRows] = useState<Row[]>([])
  const [total, setTotal] = useState(0)
  const [statusFilter, setStatusFilter] = useState('pending')
  const [limit] = useState(50)
  const [offset, setOffset] = useState(0)
  const [loading, setLoading] = useState(true)
  const [token, setToken] = useState<string | null>(null)
  const [backfillLoading, setBackfillLoading] = useState(false)
  const [backfillResult, setBackfillResult] = useState<{ updated: number; total_processed: number; need_clean: number; need_onsale: number; need_product_id: number; message: string } | null>(null)
  const [dedupeLoading, setDedupeLoading] = useState(false)
  const [categories, setCategories] = useState<{ id: string; name: string; path: string; level: number; parent_id: string | null }[]>([])
  const [error, setError] = useState<string | null>(null)
  const [successMessage, setSuccessMessage] = useState<string | null>(null)
  const [confirmingId, setConfirmingId] = useState<string | null>(null)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [similarTo, setSimilarTo] = useState<string | null>(null)
  // 本地编辑值，避免 onChange 触发 PATCH 导致整表刷新
  const [editedNormalizedName, setEditedNormalizedName] = useState<Record<string, string>>({})
  const [editedCategoryL1, setEditedCategoryL1] = useState<Record<string, string>>({})
  const [editedCategoryL2, setEditedCategoryL2] = useState<Record<string, string>>({})
  const [editedCategoryId, setEditedCategoryId] = useState<Record<string, string>>({})
  const [editedSizeQuantity, setEditedSizeQuantity] = useState<Record<string, string>>({})
  const [editedSizeUnit, setEditedSizeUnit] = useState<Record<string, string>>({})
  const [editedPackageType, setEditedPackageType] = useState<Record<string, string>>({})
  // 排序
  const [sortColumn, setSortColumn] = useState<string | null>(null)
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc')
  // 筛选
  const [filterCat1, setFilterCat1] = useState<string>('')
  const [filterCat2, setFilterCat2] = useState<string>('')
  const [filterCat3, setFilterCat3] = useState<string>('')
  const [filterUnit, setFilterUnit] = useState<string>('')
  const [filterPackage, setFilterPackage] = useState<string>('')

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
      const res = await fetch(`${apiUrl}/api/admin/classification-review?${params}`, {
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

  const fetchCategories = async () => {
    if (!token) return
    try {
      const res = await fetch(`${apiUrl}/api/admin/categories?active_only=false`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (res.ok) {
        const data = await res.json()
        setCategories(data.data || [])
      }
    } catch (_) {}
  }

  useEffect(() => {
    if (token) {
      fetchList()
      fetchCategories()
    }
  }, [token, statusFilter, offset])

  const handlePatch = async (id: string, payload: Record<string, unknown>) => {
    if (!token) return
    try {
      const res = await fetch(`${apiUrl}/api/admin/classification-review/${id}`, {
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

  const getCurrentNormalizedName = (row: Row) =>
    editedNormalizedName[row.id] ?? row.normalized_name ?? prefillNormalizedName(row.raw_product_name)

  const handleDelete = async (id: string) => {
    if (!confirm('Permanently delete this row? This cannot be undone. Existing products/rules are not affected.')) return
    if (!token) return
    setDeletingId(id)
    try {
      const res = await fetch(`${apiUrl}/api/admin/classification-review/${id}`, {
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

  const handleConfirm = async (id: string, forceDifferentName = false) => {
    if (!token) return
    const row = rows.find((r) => r.id === id)
    if (!row) return
    setConfirmingId(id)
    setSimilarTo(null)
    try {
      const currentName = getCurrentNormalizedName(row).trim()
      if (!currentName) throw new Error('normalized_name is required')
      const currentCategoryId = (editedCategoryId[id] ?? row.category_id ?? '').trim() || null
      if (!currentCategoryId) throw new Error('Please select Category III')
      const sq = (editedSizeQuantity[id] ?? (row.size_quantity != null ? String(row.size_quantity) : '')).trim()
      const num = sq ? parseFloat(sq) : NaN
      const currentQty = !isNaN(num) ? num : null
      const currentUnit = (editedSizeUnit[id] ?? row.size_unit ?? '').trim() || null
      const currentPkg = (editedPackageType[id] ?? row.package_type ?? '').trim() || null
      // 本步统一提交：先 PATCH 写入当前表单的 normalized_name / category_id / size，再 confirm（避免行上为空时后端报错）
      const patchPayload: Record<string, unknown> = {
        normalized_name: currentName,
        category_id: currentCategoryId,
        size_quantity: currentQty,
        size_unit: currentUnit || null,
        package_type: currentPkg || null,
      }
      const patchRes = await fetch(`${apiUrl}/api/admin/classification-review/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify(patchPayload),
      })
      if (!patchRes.ok) throw new Error(await patchRes.text())
      const res = await fetch(`${apiUrl}/api/admin/classification-review/${id}/confirm`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ force_different_name: forceDifferentName }),
      })
      const data = res.ok ? await res.json().catch(() => ({})) : await res.json().catch(() => ({}))
      if (res.status === 409 && data.detail?.similar_to) {
        setSimilarTo(data.detail.similar_to)
        return
      }
      if (!res.ok) throw new Error(data.detail?.message || data.detail || 'Confirm failed')
      setEditedNormalizedName((prev) => { const n = { ...prev }; delete n[id]; return n })
      setEditedCategoryL1((prev) => { const n = { ...prev }; delete n[id]; return n })
      setEditedCategoryL2((prev) => { const n = { ...prev }; delete n[id]; return n })
      setEditedCategoryId((prev) => { const n = { ...prev }; delete n[id]; return n })
      setEditedSizeQuantity((prev) => { const n = { ...prev }; delete n[id]; return n })
      setEditedSizeUnit((prev) => { const n = { ...prev }; delete n[id]; return n })
      setEditedPackageType((prev) => { const n = { ...prev }; delete n[id]; return n })
      setSuccessMessage('Confirmed')
      setError(null)
      fetchList()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Confirm failed')
      setSuccessMessage(null)
    } finally {
      setConfirmingId(null)
    }
  }

  const level1Categories = categories.filter((c) => c.level === 1)
  const level2Categories = categories.filter((c) => c.level === 2)
  const level3Categories = categories.filter((c) => c.level === 3)

  function getAncestorIds(categoryId: string | null): { l1: string | null; l2: string | null } {
    if (!categoryId) return { l1: null, l2: null }
    const l3 = categories.find((c) => c.id === categoryId)
    if (!l3 || !l3.parent_id) return { l1: null, l2: null }
    const l2 = categories.find((c) => c.id === l3.parent_id)
    if (!l2 || !l2.parent_id) return { l1: null, l2: l2?.id ?? null }
    return { l1: l2.parent_id, l2: l2.id }
  }

  // 筛选 + 排序后的行
  const displayedRows = (() => {
    let list = [...rows]
    // 筛选
    if (filterCat1) {
      list = list.filter((r) => {
        const cid = editedCategoryId[r.id] ?? r.category_id ?? null
        const { l1 } = getAncestorIds(cid)
        return l1 === filterCat1
      })
    }
    if (filterCat2) {
      list = list.filter((r) => {
        const cid = editedCategoryId[r.id] ?? r.category_id ?? null
        const { l2 } = getAncestorIds(cid)
        return l2 === filterCat2
      })
    }
    if (filterCat3) {
      list = list.filter((r) => (editedCategoryId[r.id] ?? r.category_id ?? '') === filterCat3)
    }
    if (filterUnit) list = list.filter((r) => (r.size_unit ?? '') === filterUnit)
    if (filterPackage) list = list.filter((r) => (r.package_type ?? '') === filterPackage)
    // 排序
    if (sortColumn) {
      const dir = sortDir === 'asc' ? 1 : -1
      list.sort((a, b) => {
        let va: string | number | null | undefined
        let vb: string | number | null | undefined
        switch (sortColumn) {
          case 'raw_product_name':
            va = a.raw_product_name ?? ''
            vb = b.raw_product_name ?? ''
            break
          case 'normalized_name':
            va = editedNormalizedName[a.id] ?? a.normalized_name ?? prefillNormalizedName(a.raw_product_name)
            vb = editedNormalizedName[b.id] ?? b.normalized_name ?? prefillNormalizedName(b.raw_product_name)
            break
          case 'category':
            va = getAncestorIds(editedCategoryId[a.id] ?? a.category_id ?? null).l1 ?? ''
            vb = getAncestorIds(editedCategoryId[b.id] ?? b.category_id ?? null).l1 ?? ''
            break
          case 'size_quantity':
            va = a.size_quantity ?? -Infinity
            vb = b.size_quantity ?? -Infinity
            break
          case 'size_unit':
            va = a.size_unit ?? ''
            vb = b.size_unit ?? ''
            break
          case 'package_type':
            va = a.package_type ?? ''
            vb = b.package_type ?? ''
            break
          case 'created_at':
            va = a.created_at ?? ''
            vb = b.created_at ?? ''
            break
          default:
            return 0
        }
        if (typeof va === 'string' && typeof vb === 'string') return dir * va.localeCompare(vb)
        if (typeof va === 'number' && typeof vb === 'number') return dir * (va - vb)
        return 0
      })
    }
    return list
  })()

  // 筛选下拉选项（从当前 rows 提取）
  const uniqueUnits = [...new Set(rows.map((r) => r.size_unit ?? '').filter(Boolean))].sort()
  const uniquePackages = [...new Set(rows.map((r) => r.package_type ?? '').filter(Boolean))].sort()
  const l2FilterOptions = filterCat1
    ? level2Categories.filter((c) => c.parent_id === filterCat1)
    : level2Categories
  const l3FilterOptions = filterCat2
    ? level3Categories.filter((c) => c.parent_id === filterCat2)
    : level3Categories

  const handleSort = (col: string) => {
    if (sortColumn === col) setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    else { setSortColumn(col); setSortDir('asc') }
  }

  if (!token) {
    return (
      <div className="text-center py-8 text-gray-500">Please sign in first.</div>
    )
  }

  return (
    <div>
      <h2 className="text-lg font-semibold mb-4">Classification Review</h2>
      <div className="mb-4 flex gap-4 items-center flex-wrap">
        <label className="flex items-center gap-2">
          Status:
          <select
            value={statusFilter}
            onChange={(e) => { setStatusFilter(e.target.value); setOffset(0); }}
            className="border rounded px-2 py-1"
          >
            <option value="">All</option>
            <option value="pending">pending</option>
            <option value="confirmed">confirmed</option>
            <option value="unable_to_decide">unable_to_decide</option>
            <option value="deferred">deferred</option>
            <option value="cancelled">cancelled</option>
          </select>
        </label>
        <span className="text-sm text-gray-500">{total} total</span>
      </div>
      {/* Record items 回填：方案 A 手动触发，后续可改为定时任务 */}
      <div className="mb-4 p-4 bg-gray-50 border border-gray-200 rounded">
        <p className="text-sm text-gray-700 mb-2">
          <strong>Record items backfill</strong>: One-time sync for <code className="bg-gray-200 px-1 rounded">record_items</code>. Run manually when needed.
        </p>
        <ul className="text-sm text-gray-600 list-disc list-inside mb-2">
          <li><code>product_name_clean</code>: filled from normalized product name when empty</li>
          <li><code>on_sale</code>: correct qty×price items without promo text to false</li>
          <li><code>product_id</code>: match by normalized_name + store chain and backfill</li>
        </ul>
        <p className="text-sm text-gray-500 mb-2">After confirming a batch of Classification Review, run backfill once to link new products to history record_items.</p>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            disabled={backfillLoading}
            onClick={async () => {
              if (!token) return
              setBackfillLoading(true)
              setBackfillResult(null)
              try {
                const res = await fetch(`${apiUrl}/api/admin/classification-review/backfill-record-items?limit=0&batch=200`, {
                  method: 'POST',
                  headers: { Authorization: `Bearer ${token}` },
                })
                const data = await res.json().catch(() => ({}))
                if (!res.ok) throw new Error(data.detail?.message || data.detail || 'Backfill failed')
                setBackfillResult(data)
                setSuccessMessage(data.message || `Backfilled ${data.updated ?? 0} rows`)
              } catch (e) {
                setError(e instanceof Error ? e.message : 'Backfill failed')
              } finally {
                setBackfillLoading(false)
              }
            }}
            className="px-3 py-1.5 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 disabled:opacity-50"
          >
            {backfillLoading ? 'Running…' : 'Backfill now'}
          </button>
          <button
            type="button"
            disabled={dedupeLoading}
            onClick={async () => {
              if (!token) return
              setDedupeLoading(true)
              setError(null)
              try {
                const res = await fetch(`${apiUrl}/api/admin/classification-review/dedupe`, {
                  method: 'POST',
                  headers: { Authorization: `Bearer ${token}` },
                })
                const data = await res.json().catch(() => ({}))
                if (!res.ok) throw new Error(data.detail?.message || data.detail || 'Dedupe failed')
                setSuccessMessage(data.message ?? `Removed ${data.deleted ?? 0} duplicate row(s).`)
                await fetchList()
              } catch (e) {
                setError(e instanceof Error ? e.message : '去重失败')
              } finally {
                setDedupeLoading(false)
              }
            }}
            className="px-3 py-1.5 bg-gray-600 text-white text-sm rounded hover:bg-gray-700 disabled:opacity-50"
          >
            {dedupeLoading ? 'Running…' : '去重'}
          </button>
        </div>
        {backfillResult && (
          <p className="mt-2 text-sm text-gray-600">
            This run: processed {backfillResult.total_processed}, updated {backfillResult.updated} (need_clean: {backfillResult.need_clean}, need_onsale: {backfillResult.need_onsale}, need_product_id: {backfillResult.need_product_id}).
          </p>
        )}
      </div>
      {error && (
        <div className="mb-4 p-2 bg-red-100 text-red-700 rounded text-sm flex items-center justify-between gap-2">
          <span>{error}</span>
          <button type="button" className="shrink-0 text-red-700 hover:text-red-900" onClick={() => setError(null)} aria-label="Close">×</button>
        </div>
      )}
      {successMessage && (
        <div className="mb-4 p-2 bg-green-100 text-green-800 rounded text-sm flex items-center justify-between gap-2">
          <span>{successMessage}</span>
          <button type="button" className="shrink-0 text-green-800 hover:text-green-900" onClick={() => setSuccessMessage(null)} aria-label="Close">×</button>
        </div>
      )}
      {similarTo && (
        <div className="mb-4 p-2 bg-amber-100 text-amber-800 rounded text-sm">
          Similar to existing name &quot;{similarTo}&quot;. Use current name anyway?
          <button className="ml-2 px-2 py-0.5 bg-amber-200 rounded" onClick={() => { handleConfirm(confirmingId!, true); setSimilarTo(null); }}>Use anyway</button>
          <button className="ml-2 px-2 py-0.5 rounded border" onClick={() => setSimilarTo(null)}>Cancel</button>
        </div>
      )}
      {/* 筛选：Category I/II/III, unit, package */}
      {!loading && rows.length > 0 && (
        <div className="mb-4 flex flex-wrap gap-3 items-center">
          <span className="text-gray-600 text-sm">Filter:</span>
          <select
            value={filterCat1}
            onChange={(e) => { setFilterCat1(e.target.value); setFilterCat2(''); setFilterCat3(''); }}
            className="border border-gray-200 rounded px-2 py-1 text-sm"
          >
            <option value="">Category I: All</option>
            {level1Categories.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
          <select
            value={filterCat2}
            onChange={(e) => { setFilterCat2(e.target.value); setFilterCat3(''); }}
            className="border border-gray-200 rounded px-2 py-1 text-sm"
          >
            <option value="">Category II: All</option>
            {l2FilterOptions.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
          <select
            value={filterCat3}
            onChange={(e) => setFilterCat3(e.target.value)}
            className="border border-gray-200 rounded px-2 py-1 text-sm"
          >
            <option value="">Category III: All</option>
            {l3FilterOptions.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
          <select
            value={filterUnit}
            onChange={(e) => setFilterUnit(e.target.value)}
            className="border border-gray-200 rounded px-2 py-1 text-sm"
          >
            <option value="">unit: All</option>
            {uniqueUnits.map((u) => (
              <option key={u} value={u}>{u}</option>
            ))}
          </select>
          <select
            value={filterPackage}
            onChange={(e) => setFilterPackage(e.target.value)}
            className="border border-gray-200 rounded px-2 py-1 text-sm"
          >
            <option value="">package: All</option>
            {uniquePackages.map((p) => (
              <option key={p} value={p}>{p}</option>
            ))}
          </select>
          {(filterCat1 || filterCat2 || filterCat3 || filterUnit || filterPackage) && (
            <button
              type="button"
              className="text-sm text-gray-600 hover:text-gray-800 underline"
              onClick={() => { setFilterCat1(''); setFilterCat2(''); setFilterCat3(''); setFilterUnit(''); setFilterPackage(''); }}
            >
              Clear filters
            </button>
          )}
          <span className="text-sm text-gray-500">Showing {displayedRows.length} / {rows.length}</span>
        </div>
      )}
      {loading ? (
        <p className="text-gray-500">Loading…</p>
      ) : (
        <div className="overflow-x-auto bg-white rounded-lg shadow">
          <table className="w-full table-fixed divide-y divide-gray-200 text-sm">
            <thead className="bg-gray-50">
              <tr>
                <th
                  className="px-2 py-2 text-left cursor-pointer select-none hover:bg-gray-100 w-[12%]"
                  onClick={() => handleSort('raw_product_name')}
                >
                  raw_product_name {sortColumn === 'raw_product_name' ? (sortDir === 'asc' ? '↑' : '↓') : ''}
                </th>
                <th
                  className="px-2 py-2 text-left cursor-pointer select-none hover:bg-gray-100 w-[11%]"
                  onClick={() => handleSort('normalized_name')}
                >
                  normalized_name {sortColumn === 'normalized_name' ? (sortDir === 'asc' ? '↑' : '↓') : ''}
                </th>
                <th
                  className="px-2 py-2 text-left cursor-pointer select-none hover:bg-gray-100 w-[11%]"
                  onClick={() => handleSort('category')}
                >
                  Category I {sortColumn === 'category' ? (sortDir === 'asc' ? '↑' : '↓') : ''}
                </th>
                <th className="px-2 py-2 text-left w-[11%]">Category II</th>
                <th className="px-2 py-2 text-left w-[11%]">Category III</th>
                <th
                  className="px-2 py-2 text-left cursor-pointer select-none hover:bg-gray-100 w-[6%]"
                  onClick={() => handleSort('size_quantity')}
                >
                  size_qty {sortColumn === 'size_quantity' ? (sortDir === 'asc' ? '↑' : '↓') : ''}
                </th>
                <th
                  className="px-2 py-2 text-left cursor-pointer select-none hover:bg-gray-100 w-[5%]"
                  onClick={() => handleSort('size_unit')}
                >
                  unit {sortColumn === 'size_unit' ? (sortDir === 'asc' ? '↑' : '↓') : ''}
                </th>
                <th
                  className="px-2 py-2 text-left cursor-pointer select-none hover:bg-gray-100 w-[7%]"
                  onClick={() => handleSort('package_type')}
                >
                  package {sortColumn === 'package_type' ? (sortDir === 'asc' ? '↑' : '↓') : ''}
                </th>
                <th className="px-2 py-2 text-left w-[7%]">status</th>
                <th className="px-2 py-2 text-left w-[13%]">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {displayedRows.map((r) => (
                <tr key={r.id}>
                  <td className="px-2 py-2 truncate" title={r.raw_product_name}>{r.raw_product_name}</td>
                  <td className="px-2 py-2 overflow-hidden">
                    {r.status === 'confirmed' ? (
                      <span className="truncate block" title={editedNormalizedName[r.id] ?? r.normalized_name ?? prefillNormalizedName(r.raw_product_name)}>{editedNormalizedName[r.id] ?? r.normalized_name ?? prefillNormalizedName(r.raw_product_name)}</span>
                    ) : (
                      <input
                        className="border border-gray-200 rounded px-1 w-full max-w-[7rem] focus:ring-1 focus:ring-gray-300 focus:border-gray-300"
                        value={editedNormalizedName[r.id] ?? r.normalized_name ?? prefillNormalizedName(r.raw_product_name)}
                        onChange={(e) => setEditedNormalizedName((prev) => ({ ...prev, [r.id]: e.target.value }))}
                      />
                    )}
                  </td>
                  <CategoryCascade
                    row={r}
                    level1={level1Categories}
                    level2={level2Categories}
                    level3={level3Categories}
                    getAncestorIds={getAncestorIds}
                    editedL1={editedCategoryL1}
                    editedL2={editedCategoryL2}
                    editedCategoryId={editedCategoryId}
                    onEditedL1={(id, val) => setEditedCategoryL1((p) => ({ ...p, [id]: val }))}
                    onEditedL2={(id, val) => setEditedCategoryL2((p) => ({ ...p, [id]: val }))}
                    onEditedCategoryId={(id, val) => setEditedCategoryId((p) => ({ ...p, [id]: val }))}
                    disabled={r.status === 'confirmed'}
                  />
                  <td className="px-2 py-2">
                    {r.status === 'confirmed' ? (
                      <span>{editedSizeQuantity[r.id] ?? (r.size_quantity != null ? String(r.size_quantity) : '')}</span>
                    ) : (
                      <input
                        className="border border-gray-200 rounded px-1 w-full max-w-[3rem] focus:ring-1 focus:ring-gray-300 focus:border-gray-300"
                        type="text"
                        inputMode="decimal"
                        placeholder="3.5"
                        value={editedSizeQuantity[r.id] ?? (r.size_quantity != null ? String(r.size_quantity) : '')}
                        onChange={(e) => setEditedSizeQuantity((p) => ({ ...p, [r.id]: e.target.value }))}
                      />
                    )}
                  </td>
                  <td className="px-2 py-2">
                    {r.status === 'confirmed' ? (
                      <span>{editedSizeUnit[r.id] ?? r.size_unit ?? ''}</span>
                    ) : (
                      <input
                        className="border border-gray-200 rounded px-1 w-full max-w-[2.5rem] focus:ring-1 focus:ring-gray-300 focus:border-gray-300"
                        placeholder="oz"
                        value={editedSizeUnit[r.id] ?? r.size_unit ?? ''}
                        onChange={(e) => setEditedSizeUnit((p) => ({ ...p, [r.id]: e.target.value }))}
                      />
                    )}
                  </td>
                  <td className="px-2 py-2">
                    {r.status === 'confirmed' ? (
                      <span>{editedPackageType[r.id] ?? r.package_type ?? ''}</span>
                    ) : (
                      <input
                        className="border border-gray-200 rounded px-1 w-full max-w-[4rem] focus:ring-1 focus:ring-gray-300 focus:border-gray-300"
                        placeholder="bottle"
                        value={editedPackageType[r.id] ?? r.package_type ?? ''}
                        onChange={(e) => setEditedPackageType((p) => ({ ...p, [r.id]: e.target.value }))}
                      />
                    )}
                  </td>
                  <td className="px-2 py-2">
                    {r.status === 'confirmed' ? (
                      <button
                        className="px-2 py-1 bg-red-100 rounded text-red-800 hover:bg-red-200"
                        onClick={() => handlePatch(r.id, { status: 'pending' })}
                      >
                        Modification
                      </button>
                    ) : (
                      <select
                        className="border border-gray-200 rounded px-1 w-full max-w-[4.5rem] text-xs focus:ring-1 focus:ring-gray-300 focus:border-gray-300"
                        value={r.status}
                        onChange={(e) => handlePatch(r.id, { status: e.target.value })}
                        title={r.status}
                      >
                        <option value="pending">pending</option>
                        <option value="unable_to_decide">unable_to_decide</option>
                        <option value="deferred">deferred</option>
                        <option value="cancelled">cancelled</option>
                      </select>
                    )}
                  </td>
                  <td className="px-2 py-2 flex flex-col items-stretch gap-1">
                    {r.status === 'pending' && (
                      <button
                        className="px-2 py-1 bg-green-100 rounded text-green-800 disabled:opacity-50"
                        disabled={confirmingId !== null || !getCurrentNormalizedName(r).trim() || !(editedCategoryId[r.id] ?? r.category_id)}
                        onClick={() => handleConfirm(r.id)}
                      >
                        {confirmingId === r.id ? '...' : 'Confirm'}
                      </button>
                    )}
                    {(r.status === 'cancelled' || r.status === 'deferred') && (
                      <button
                        className="px-2 py-1 border rounded text-gray-600"
                        onClick={() => handlePatch(r.id, { status: 'pending' })}
                      >
                        Reopen
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={() => handleDelete(r.id)}
                      disabled={deletingId === r.id}
                      className="px-2 py-1 text-red-600 hover:underline disabled:opacity-50"
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
      {total > limit && (
        <div className="mt-4 flex gap-2">
          <button className="px-3 py-1 border rounded disabled:opacity-50" disabled={offset === 0} onClick={() => setOffset((o) => Math.max(0, o - limit))}>Previous</button>
          <button className="px-3 py-1 border rounded disabled:opacity-50" disabled={offset + limit >= total} onClick={() => setOffset((o) => o + limit)}>Next</button>
        </div>
      )}

    </div>
  )
}
