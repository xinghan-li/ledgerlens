'use client'

import { useEffect, useState } from 'react'
import { createClient } from '@/lib/supabase'

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
        <td className="px-3 py-2">{l1Name}</td>
        <td className="px-3 py-2">{l2Name}</td>
        <td className="px-3 py-2">{l3Name}</td>
      </>
    )
  }

  return (
    <>
      <td className="px-3 py-2">
        <select
          className="border border-gray-200 rounded px-1 w-28 focus:ring-1 focus:ring-gray-300 focus:border-gray-300"
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
      <td className="px-3 py-2">
        <select
          className="border border-gray-200 rounded px-1 w-28 focus:ring-1 focus:ring-gray-300 focus:border-gray-300"
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
      <td className="px-3 py-2">
        <select
          className="border border-gray-200 rounded px-1 w-36 focus:ring-1 focus:ring-gray-300 focus:border-gray-300"
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
      const res = await fetch(`${apiUrl}/api/admin/classification-review?${params}`, {
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
      setError(e instanceof Error ? e.message : '更新失败')
    }
  }

  const getCurrentNormalizedName = (row: Row) =>
    editedNormalizedName[row.id] ?? row.normalized_name ?? prefillNormalizedName(row.raw_product_name)

  const handleDelete = async (id: string) => {
    if (!confirm('确定要永久删除这一条吗？删除后无法恢复，且不会影响已录入的 product / 规则。')) return
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
      setError(e instanceof Error ? e.message : '删除失败')
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
      if (!currentName) throw new Error('normalized_name 不能为空')
      const currentCategoryId = (editedCategoryId[id] ?? row.category_id ?? '').trim() || null
      if (!currentCategoryId) throw new Error('请选择 Category III')
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
      if (!res.ok) throw new Error(data.detail?.message || data.detail || 'Confirm 失败')
      setEditedNormalizedName((prev) => { const n = { ...prev }; delete n[id]; return n })
      setEditedCategoryL1((prev) => { const n = { ...prev }; delete n[id]; return n })
      setEditedCategoryL2((prev) => { const n = { ...prev }; delete n[id]; return n })
      setEditedCategoryId((prev) => { const n = { ...prev }; delete n[id]; return n })
      setEditedSizeQuantity((prev) => { const n = { ...prev }; delete n[id]; return n })
      setEditedSizeUnit((prev) => { const n = { ...prev }; delete n[id]; return n })
      setEditedPackageType((prev) => { const n = { ...prev }; delete n[id]; return n })
      setSuccessMessage('已确认')
      setError(null)
      fetchList()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Confirm 失败')
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
      <div className="text-center py-8 text-gray-500">请先登录</div>
    )
  }

  return (
    <div>
      <h2 className="text-lg font-semibold mb-4">分类审核 (Classification Review)</h2>
      <div className="mb-4 flex gap-4 items-center flex-wrap">
        <label className="flex items-center gap-2">
          状态：
          <select
            value={statusFilter}
            onChange={(e) => { setStatusFilter(e.target.value); setOffset(0); }}
            className="border rounded px-2 py-1"
          >
            <option value="">全部</option>
            <option value="pending">pending</option>
            <option value="confirmed">confirmed</option>
            <option value="unable_to_decide">unable_to_decide</option>
            <option value="deferred">deferred</option>
            <option value="cancelled">cancelled</option>
          </select>
        </label>
        <span className="text-sm text-gray-500">共 {total} 条</span>
      </div>
      {error && (
        <div className="mb-4 p-2 bg-red-100 text-red-700 rounded text-sm flex items-center justify-between gap-2">
          <span>{error}</span>
          <button type="button" className="shrink-0 text-red-700 hover:text-red-900" onClick={() => setError(null)} aria-label="关闭">×</button>
        </div>
      )}
      {successMessage && (
        <div className="mb-4 p-2 bg-green-100 text-green-800 rounded text-sm flex items-center justify-between gap-2">
          <span>{successMessage}</span>
          <button type="button" className="shrink-0 text-green-800 hover:text-green-900" onClick={() => setSuccessMessage(null)} aria-label="关闭">×</button>
        </div>
      )}
      {similarTo && (
        <div className="mb-4 p-2 bg-amber-100 text-amber-800 rounded text-sm">
          与已有名称 &quot;{similarTo}&quot; 相似。是否仍要使用当前名称？
          <button className="ml-2 px-2 py-0.5 bg-amber-200 rounded" onClick={() => { handleConfirm(confirmingId!, true); setSimilarTo(null); }}>坚持使用</button>
          <button className="ml-2 px-2 py-0.5 rounded border" onClick={() => setSimilarTo(null)}>取消</button>
        </div>
      )}
      {/* 筛选：Category I/II/III, unit, package */}
      {!loading && rows.length > 0 && (
        <div className="mb-4 flex flex-wrap gap-3 items-center">
          <span className="text-gray-600 text-sm">筛选：</span>
          <select
            value={filterCat1}
            onChange={(e) => { setFilterCat1(e.target.value); setFilterCat2(''); setFilterCat3(''); }}
            className="border border-gray-200 rounded px-2 py-1 text-sm"
          >
            <option value="">Category I: 全部</option>
            {level1Categories.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
          <select
            value={filterCat2}
            onChange={(e) => { setFilterCat2(e.target.value); setFilterCat3(''); }}
            className="border border-gray-200 rounded px-2 py-1 text-sm"
          >
            <option value="">Category II: 全部</option>
            {l2FilterOptions.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
          <select
            value={filterCat3}
            onChange={(e) => setFilterCat3(e.target.value)}
            className="border border-gray-200 rounded px-2 py-1 text-sm"
          >
            <option value="">Category III: 全部</option>
            {l3FilterOptions.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
          <select
            value={filterUnit}
            onChange={(e) => setFilterUnit(e.target.value)}
            className="border border-gray-200 rounded px-2 py-1 text-sm"
          >
            <option value="">unit: 全部</option>
            {uniqueUnits.map((u) => (
              <option key={u} value={u}>{u}</option>
            ))}
          </select>
          <select
            value={filterPackage}
            onChange={(e) => setFilterPackage(e.target.value)}
            className="border border-gray-200 rounded px-2 py-1 text-sm"
          >
            <option value="">package: 全部</option>
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
              清除筛选
            </button>
          )}
          <span className="text-sm text-gray-500">显示 {displayedRows.length} / {rows.length} 条</span>
        </div>
      )}
      {loading ? (
        <p className="text-gray-500">加载中...</p>
      ) : (
        <div className="overflow-x-auto bg-white rounded-lg shadow">
          <table className="min-w-full divide-y divide-gray-200 text-sm">
            <thead className="bg-gray-50">
              <tr>
                <th
                  className="px-3 py-2 text-left cursor-pointer select-none hover:bg-gray-100"
                  onClick={() => handleSort('raw_product_name')}
                >
                  raw_product_name {sortColumn === 'raw_product_name' ? (sortDir === 'asc' ? '↑' : '↓') : ''}
                </th>
                <th
                  className="px-3 py-2 text-left cursor-pointer select-none hover:bg-gray-100"
                  onClick={() => handleSort('normalized_name')}
                >
                  normalized_name {sortColumn === 'normalized_name' ? (sortDir === 'asc' ? '↑' : '↓') : ''}
                </th>
                <th
                  className="px-3 py-2 text-left cursor-pointer select-none hover:bg-gray-100"
                  onClick={() => handleSort('category')}
                >
                  Category I {sortColumn === 'category' ? (sortDir === 'asc' ? '↑' : '↓') : ''}
                </th>
                <th className="px-3 py-2 text-left">Category II</th>
                <th className="px-3 py-2 text-left">Category III</th>
                <th
                  className="px-3 py-2 text-left cursor-pointer select-none hover:bg-gray-100"
                  onClick={() => handleSort('size_quantity')}
                >
                  size_qty {sortColumn === 'size_quantity' ? (sortDir === 'asc' ? '↑' : '↓') : ''}
                </th>
                <th
                  className="px-3 py-2 text-left cursor-pointer select-none hover:bg-gray-100"
                  onClick={() => handleSort('size_unit')}
                >
                  unit {sortColumn === 'size_unit' ? (sortDir === 'asc' ? '↑' : '↓') : ''}
                </th>
                <th
                  className="px-3 py-2 text-left cursor-pointer select-none hover:bg-gray-100"
                  onClick={() => handleSort('package_type')}
                >
                  package {sortColumn === 'package_type' ? (sortDir === 'asc' ? '↑' : '↓') : ''}
                </th>
                <th className="px-3 py-2 text-left">status</th>
                <th className="px-3 py-2 text-left">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {displayedRows.map((r) => (
                <tr key={r.id}>
                  <td className="px-3 py-2">{r.raw_product_name}</td>
                  <td className="px-3 py-2">
                    {r.status === 'confirmed' ? (
                      <span>{editedNormalizedName[r.id] ?? r.normalized_name ?? prefillNormalizedName(r.raw_product_name)}</span>
                    ) : (
                      <input
                        className="border border-gray-200 rounded px-1 w-40 focus:ring-1 focus:ring-gray-300 focus:border-gray-300"
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
                  <td className="px-3 py-2">
                    {r.status === 'confirmed' ? (
                      <span>{editedSizeQuantity[r.id] ?? (r.size_quantity != null ? String(r.size_quantity) : '')}</span>
                    ) : (
                      <input
                        className="border border-gray-200 rounded px-1 w-16 focus:ring-1 focus:ring-gray-300 focus:border-gray-300"
                        type="text"
                        inputMode="decimal"
                        placeholder="3.5"
                        value={editedSizeQuantity[r.id] ?? (r.size_quantity != null ? String(r.size_quantity) : '')}
                        onChange={(e) => setEditedSizeQuantity((p) => ({ ...p, [r.id]: e.target.value }))}
                      />
                    )}
                  </td>
                  <td className="px-3 py-2">
                    {r.status === 'confirmed' ? (
                      <span>{editedSizeUnit[r.id] ?? r.size_unit ?? ''}</span>
                    ) : (
                      <input
                        className="border border-gray-200 rounded px-1 w-16 focus:ring-1 focus:ring-gray-300 focus:border-gray-300"
                        placeholder="oz"
                        value={editedSizeUnit[r.id] ?? r.size_unit ?? ''}
                        onChange={(e) => setEditedSizeUnit((p) => ({ ...p, [r.id]: e.target.value }))}
                      />
                    )}
                  </td>
                  <td className="px-3 py-2">
                    {r.status === 'confirmed' ? (
                      <span>{editedPackageType[r.id] ?? r.package_type ?? ''}</span>
                    ) : (
                      <input
                        className="border border-gray-200 rounded px-1 w-16 focus:ring-1 focus:ring-gray-300 focus:border-gray-300"
                        placeholder="bottle"
                        value={editedPackageType[r.id] ?? r.package_type ?? ''}
                        onChange={(e) => setEditedPackageType((p) => ({ ...p, [r.id]: e.target.value }))}
                      />
                    )}
                  </td>
                  <td className="px-3 py-2">
                    {r.status === 'confirmed' ? (
                      <button
                        className="px-2 py-1 bg-red-100 rounded text-red-800 hover:bg-red-200"
                        onClick={() => handlePatch(r.id, { status: 'pending' })}
                      >
                        Modification
                      </button>
                    ) : (
                      <select
                        className="border border-gray-200 rounded px-1 focus:ring-1 focus:ring-gray-300 focus:border-gray-300"
                        value={r.status}
                        onChange={(e) => handlePatch(r.id, { status: e.target.value })}
                      >
                        <option value="pending">pending</option>
                        <option value="unable_to_decide">unable_to_decide</option>
                        <option value="deferred">deferred</option>
                        <option value="cancelled">cancelled</option>
                      </select>
                    )}
                  </td>
                  <td className="px-3 py-2 flex flex-wrap items-center gap-2">
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
                        重开
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={() => handleDelete(r.id)}
                      disabled={deletingId === r.id}
                      className="px-2 py-1 text-red-600 hover:underline disabled:opacity-50"
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
      {total > limit && (
        <div className="mt-4 flex gap-2">
          <button className="px-3 py-1 border rounded disabled:opacity-50" disabled={offset === 0} onClick={() => setOffset((o) => Math.max(0, o - limit))}>上一页</button>
          <button className="px-3 py-1 border rounded disabled:opacity-50" disabled={offset + limit >= total} onClick={() => setOffset((o) => o + limit)}>下一页</button>
        </div>
      )}

    </div>
  )
}
