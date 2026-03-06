'use client'

import { useEffect, useState } from 'react'
import { getFirebaseAuth } from '@/lib/firebase'
import { onAuthStateChanged } from 'firebase/auth'
import { useApiUrl } from '@/lib/api-url-context'

type Category = {
  id: string
  parent_id: string | null
  name: string
  path: string | null
  level: number
  is_active: boolean
  is_system: boolean
}

export default function AdminCategoriesPage() {
  const apiBaseUrl = useApiUrl()
  const [list, setList] = useState<Category[]>([])
  const [token, setToken] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Add new: L1
  const [newL1Name, setNewL1Name] = useState('')
  // Add new: L2
  const [newL2ParentId, setNewL2ParentId] = useState<string>('')
  const [newL2Name, setNewL2Name] = useState('')
  // Add new: L3
  const [newL3ParentId, setNewL3ParentId] = useState<string>('')
  const [newL3Name, setNewL3Name] = useState('')

  const [editingId, setEditingId] = useState<string | null>(null)
  const [editName, setEditName] = useState('')

  // Hard delete modal
  const [hardDeleteCategory, setHardDeleteCategory] = useState<Category | null>(null)
  const [hardDeleteAction, setHardDeleteAction] = useState<'release' | 'reassign' | null>(null)
  const [reassignL1Id, setReassignL1Id] = useState<string>('')
  const [reassignL2Id, setReassignL2Id] = useState<string>('')
  const [reassignL3Id, setReassignL3Id] = useState<string>('')
  const [hardDeleteSubmitting, setHardDeleteSubmitting] = useState(false)

  useEffect(() => {
    const auth = getFirebaseAuth()
    const unsubscribe = onAuthStateChanged(auth, async (user) => {
      setToken(user ? await user.getIdToken() : null)
    })
    return () => unsubscribe()
  }, [])

  const fetchCategories = async (showLoading = true) => {
    if (!token) return
    if (showLoading) setLoading(true)
    setError(null)
    try {
      const res = await fetch(`${apiBaseUrl}/api/admin/categories?active_only=false`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (!res.ok) throw new Error(await res.text())
      const data = await res.json()
      setList(data.data || [])
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load')
    } finally {
      if (showLoading) setLoading(false)
    }
  }

  useEffect(() => {
    if (token) fetchCategories()
  }, [token])

  const handleCreateL1 = async () => {
    if (!token || !newL1Name.trim()) return
    setError(null)
    try {
      const res = await fetch(`${apiBaseUrl}/api/admin/categories`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ parent_id: null, name: newL1Name.trim(), level: 1 }),
      })
      const data = await res.json().catch(() => ({}))
      if (res.status === 409) {
        setError('A category with this name already exists at this level')
        return
      }
      if (!res.ok) throw new Error(data.detail || 'Create failed')
      setNewL1Name('')
      if (data?.id) {
        setList((prev) => [...prev, { ...data, parent_id: null, path: (data.name || '').trim().toLowerCase(), level: 1, is_active: true, is_system: false } as Category])
      } else {
        fetchCategories(false)
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Create failed')
    }
  }

  const handleCreateL2 = async () => {
    if (!token || !newL2Name.trim() || !newL2ParentId) return
    setError(null)
    try {
      const res = await fetch(`${apiBaseUrl}/api/admin/categories`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ parent_id: newL2ParentId, name: newL2Name.trim(), level: 2 }),
      })
      const data = await res.json().catch(() => ({}))
      if (res.status === 409) {
        setError('A category with this name already exists at this level')
        return
      }
      if (!res.ok) throw new Error(data.detail || 'Create failed')
      setNewL2Name('')
      if (data?.id) {
        setList((prev) => [...prev, { id: data.id, parent_id: data.parent_id ?? newL2ParentId, name: data.name ?? newL2Name.trim(), path: data.path ?? null, level: 2, is_active: true, is_system: data.is_system ?? false } as Category])
      } else {
        fetchCategories(false)
      }
      setNewL2ParentId('')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Create failed')
    }
  }

  const handleCreateL3 = async () => {
    if (!token || !newL3Name.trim() || !newL3ParentId) return
    setError(null)
    try {
      const res = await fetch(`${apiBaseUrl}/api/admin/categories`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ parent_id: newL3ParentId, name: newL3Name.trim(), level: 3 }),
      })
      const data = await res.json().catch(() => ({}))
      if (res.status === 409) {
        setError('A category with this name already exists at this level')
        return
      }
      if (!res.ok) throw new Error(data.detail || 'Create failed')
      setNewL3Name('')
      if (data?.id) {
        setList((prev) => [...prev, { id: data.id, parent_id: data.parent_id ?? newL3ParentId, name: data.name ?? newL3Name.trim(), path: data.path ?? null, level: 3, is_active: true, is_system: data.is_system ?? false } as Category])
      } else {
        fetchCategories(false)
      }
      setNewL3ParentId('')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Create failed')
    }
  }

  const handleUpdate = async () => {
    if (!token || !editingId || !editName.trim()) return
    setError(null)
    try {
      const res = await fetch(`${apiBaseUrl}/api/admin/categories/${editingId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ name: editName.trim() }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.detail || await res.text())
      setEditingId(null)
      setEditName('')
      if (data?.id) {
        setList((prev) => prev.map((c) => (c.id === data.id ? { ...c, name: data.name ?? editName.trim(), path: data.path ?? c.path } : c)))
      } else {
        fetchCategories(false)
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Update failed')
    }
  }

  const handleDelete = async (id: string) => {
    if (!token || !confirm('Soft-delete this category?')) return
    setError(null)
    try {
      const res = await fetch(`${apiBaseUrl}/api/admin/categories/${id}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` },
      })
      if (!res.ok) throw new Error(await res.text())
      setList((prev) => prev.map((c) => (c.id === id ? { ...c, is_active: false } : c)))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Delete failed')
    }
  }

  /** Reset options when opening hard-delete modal */
  const openHardDeleteModal = (cat: Category) => {
    setHardDeleteCategory(cat)
    setHardDeleteAction(null)
    setReassignL1Id('')
    setReassignL2Id('')
    setReassignL3Id('')
  }

  const closeHardDeleteModal = () => {
    setHardDeleteCategory(null)
    setHardDeleteAction(null)
    setReassignL1Id('')
    setReassignL2Id('')
    setReassignL3Id('')
  }

  /** 被删分类及其所有后代 id（用于 reassign 时从下拉中排除） */
  const getSelfAndDescendantIds = (cat: Category, all: Category[]): Set<string> => {
    const ids = new Set<string>()
    ids.add(cat.id)
    const addChildren = (parentId: string) => {
      for (const c of all) {
        if (c.parent_id === parentId) {
          ids.add(c.id)
          addChildren(c.id)
        }
      }
    }
    addChildren(cat.id)
    return ids
  }

  const canConfirmHardDelete =
    hardDeleteAction === 'release' ||
    (hardDeleteAction === 'reassign' && !!reassignL3Id)

  const handleConfirmHardDelete = async () => {
    if (!token || !hardDeleteCategory || !canConfirmHardDelete) return
    setError(null)
    setHardDeleteSubmitting(true)
    try {
      const body: { action: string; target_category_id?: string } = { action: hardDeleteAction! }
      if (hardDeleteAction === 'reassign') body.target_category_id = reassignL3Id
      const res = await fetch(`${apiBaseUrl}/api/admin/categories/${hardDeleteCategory.id}/hard-delete`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify(body),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.detail || data.message || await res.text())
      closeHardDeleteModal()
      await fetchCategories(false)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Hard delete failed')
    } finally {
      setHardDeleteSubmitting(false)
    }
  }

  const l1 = list.filter((c) => c.level === 1)
  const l2 = list.filter((c) => c.level === 2)
  const l3 = list.filter((c) => c.level === 3)
  // Category II 列表按所选 L1 过滤；Category III 列表按所选 L2 过滤
  const l2Filtered = newL2ParentId ? l2.filter((c) => c.parent_id === newL2ParentId) : l2
  const l3Filtered = newL3ParentId ? l3.filter((c) => c.parent_id === newL3ParentId) : l3

  if (!token) return <div className="text-center py-8 text-theme-mid">Please sign in first.</div>

  return (
    <div>
      <h2 className="font-heading text-lg sm:text-xl font-semibold mb-4 text-theme-dark">Category Management</h2>
      {error && (
        <div className="mb-4 p-3 sm:p-4 bg-theme-red/10 border border-theme-red/30 rounded-lg text-sm text-theme-red">
          {error}
        </div>
      )}
      {loading ? (
        <p className="text-theme-mid">Loading…</p>
      ) : (
        <div className="grid grid-cols-3 gap-6">
          {/* Category I (L1) */}
          <div className="bg-white rounded-xl shadow p-4 sm:p-6 overflow-hidden">
            <h3 className="font-heading font-semibold mb-3 text-theme-dark">Category I</h3>
            <div className="mb-3 flex gap-2 items-center">
              <input
                className="border border-theme-light-gray rounded-lg px-2 py-1.5 flex-1 text-sm text-theme-dark bg-white focus:outline-none focus:ring-1 focus:ring-theme-mid"
                placeholder="New L1 category name"
                value={newL1Name}
                onChange={(e) => setNewL1Name(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleCreateL1()}
              />
              <button className="btn-primary px-3 py-1.5 text-sm whitespace-nowrap disabled:opacity-50" onClick={handleCreateL1} disabled={!newL1Name.trim()}>
                Add
              </button>
            </div>
            <ul className="space-y-1 text-sm max-h-80 overflow-y-auto text-theme-dark">
              {l1.map((c) => (
                <li key={c.id} className="flex items-center gap-1 group py-0.5">
                  {editingId === c.id ? (
                    <>
                      <input className="border border-theme-light-gray rounded-lg px-1.5 py-0.5 flex-1 text-sm text-theme-dark" value={editName} onChange={(e) => setEditName(e.target.value)} />
                      <button className="px-1.5 text-theme-orange font-medium hover:underline" onClick={handleUpdate}>Save</button>
                      <button className="px-1.5 text-theme-mid font-medium hover:underline" onClick={() => { setEditingId(null); setEditName(''); }}>Cancel</button>
                    </>
                  ) : (
                    <>
                      <span className={!c.is_active ? 'text-theme-mid' : ''}>{c.name}</span>
                      {!c.is_active && <span className="text-xs text-theme-mid">(disabled)</span>}
                      <button className="opacity-0 group-hover:opacity-100 px-1 text-theme-mid hover:text-theme-dark text-sm" onClick={() => { setEditingId(c.id); setEditName(c.name); }}>Edit</button>
                      {c.is_active ? (
                        <button className="opacity-0 group-hover:opacity-100 px-1 text-theme-red font-medium text-sm" onClick={() => handleDelete(c.id)}>Disabled</button>
                      ) : (
                        <button className="opacity-0 group-hover:opacity-100 px-1 text-theme-red font-medium text-sm" onClick={() => openHardDeleteModal(c)}>Deleted</button>
                      )}
                    </>
                  )}
                </li>
              ))}
            </ul>
          </div>

          {/* Category II (L2) */}
          <div className="bg-white rounded-xl shadow p-4 sm:p-6 overflow-hidden">
            <h3 className="font-heading font-semibold mb-3 text-theme-dark">Category II</h3>
            <div className="mb-3 space-y-2">
              <select
                className="border border-theme-light-gray rounded-lg px-2 py-1.5 w-full text-sm text-theme-dark bg-white focus:outline-none focus:ring-1 focus:ring-theme-mid"
                value={newL2ParentId}
                onChange={(e) => setNewL2ParentId(e.target.value)}
              >
                <option value="">Select parent (L1)</option>
                {l1.filter((c) => c.is_active).map((c) => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
              </select>
              <div className="flex gap-2 items-center">
                <input
                  className="border border-theme-light-gray rounded-lg px-2 py-1.5 flex-1 text-sm text-theme-dark bg-white focus:outline-none focus:ring-1 focus:ring-theme-mid"
                  placeholder="New L2 category name"
                  value={newL2Name}
                  onChange={(e) => setNewL2Name(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleCreateL2()}
                />
                <button className="btn-primary px-3 py-1.5 text-sm whitespace-nowrap disabled:opacity-50" onClick={handleCreateL2} disabled={!newL2Name.trim() || !newL2ParentId}>
                  Add
                </button>
              </div>
            </div>
            <ul className="space-y-1 text-sm max-h-80 overflow-y-auto text-theme-dark">
              {l2Filtered.map((c) => (
                <li key={c.id} className="flex items-center gap-1 group py-0.5">
                  {editingId === c.id ? (
                    <>
                      <input className="border border-theme-light-gray rounded-lg px-1.5 py-0.5 flex-1 text-sm text-theme-dark" value={editName} onChange={(e) => setEditName(e.target.value)} />
                      <button className="px-1.5 text-theme-orange font-medium hover:underline" onClick={handleUpdate}>Save</button>
                      <button className="px-1.5 text-theme-mid font-medium hover:underline" onClick={() => { setEditingId(null); setEditName(''); }}>Cancel</button>
                    </>
                  ) : (
                    <>
                      <span className={!c.is_active ? 'text-theme-mid' : ''}>{c.path || c.name}</span>
                      {!c.is_active && <span className="text-xs text-theme-mid">(disabled)</span>}
                      <button className="opacity-0 group-hover:opacity-100 px-1 text-theme-mid hover:text-theme-dark text-sm" onClick={() => { setEditingId(c.id); setEditName(c.name); }}>Edit</button>
                      {c.is_active ? (
                        <button className="opacity-0 group-hover:opacity-100 px-1 text-theme-red font-medium text-sm" onClick={() => handleDelete(c.id)}>Disabled</button>
                      ) : (
                        <button className="opacity-0 group-hover:opacity-100 px-1 text-theme-red font-medium text-sm" onClick={() => openHardDeleteModal(c)}>Deleted</button>
                      )}
                    </>
                  )}
                </li>
              ))}
            </ul>
          </div>

          {/* Category III (L3) */}
          <div className="bg-white rounded-xl shadow p-4 sm:p-6 overflow-hidden">
            <h3 className="font-heading font-semibold mb-3 text-theme-dark">Category III</h3>
            <div className="mb-3 space-y-2">
              <select
                className="border border-theme-light-gray rounded-lg px-2 py-1.5 w-full text-sm text-theme-dark bg-white focus:outline-none focus:ring-1 focus:ring-theme-mid"
                value={newL3ParentId}
                onChange={(e) => setNewL3ParentId(e.target.value)}
              >
                <option value="">Select parent (L2)</option>
                {l2.filter((c) => c.is_active).map((c) => (
                  <option key={c.id} value={c.id}>{c.path || c.name}</option>
                ))}
              </select>
              <div className="flex gap-2 items-center">
                <input
                  className="border border-theme-light-gray rounded-lg px-2 py-1.5 flex-1 text-sm text-theme-dark bg-white focus:outline-none focus:ring-1 focus:ring-theme-mid"
                  placeholder="New L3 category name"
                  value={newL3Name}
                  onChange={(e) => setNewL3Name(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleCreateL3()}
                />
                <button className="btn-primary px-3 py-1.5 text-sm whitespace-nowrap disabled:opacity-50" onClick={handleCreateL3} disabled={!newL3Name.trim() || !newL3ParentId}>
                  Add
                </button>
              </div>
            </div>
            <ul className="space-y-1 text-sm max-h-80 overflow-y-auto text-theme-dark">
              {l3Filtered.map((c) => (
                <li key={c.id} className="flex items-center gap-1 group py-0.5">
                  {editingId === c.id ? (
                    <>
                      <input className="border border-theme-light-gray rounded-lg px-1.5 py-0.5 flex-1 text-sm text-theme-dark" value={editName} onChange={(e) => setEditName(e.target.value)} />
                      <button className="px-1.5 text-theme-orange font-medium hover:underline" onClick={handleUpdate}>Save</button>
                      <button className="px-1.5 text-theme-mid font-medium hover:underline" onClick={() => { setEditingId(null); setEditName(''); }}>Cancel</button>
                    </>
                  ) : (
                    <>
                      <span className={!c.is_active ? 'text-theme-mid' : ''}>{c.path || c.name}</span>
                      {!c.is_active && <span className="text-xs text-theme-mid">(disabled)</span>}
                      <button className="opacity-0 group-hover:opacity-100 px-1 text-theme-mid hover:text-theme-dark text-sm" onClick={() => { setEditingId(c.id); setEditName(c.name); }}>Edit</button>
                      {c.is_active ? (
                        <button className="opacity-0 group-hover:opacity-100 px-1 text-theme-red font-medium text-sm" onClick={() => handleDelete(c.id)}>Disabled</button>
                      ) : (
                        <button className="opacity-0 group-hover:opacity-100 px-1 text-theme-red font-medium text-sm" onClick={() => openHardDeleteModal(c)}>Deleted</button>
                      )}
                    </>
                  )}
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}

      {/* Hard delete confirmation modal — styling matches dashboard (rounded-xl, font-heading, design tokens) */}
      {hardDeleteCategory && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-theme-black/40 p-4" onClick={(e) => e.target === e.currentTarget && closeHardDeleteModal()}>
          <div className="bg-white rounded-xl shadow-lg p-5 sm:p-6 max-w-md w-full border border-theme-light-gray/50" onClick={(e) => e.stopPropagation()}>
            <h3 className="font-heading font-semibold text-lg text-theme-dark mb-2">Confirm hard delete</h3>
            <p className="text-sm text-theme-dark/90 mb-4">
              Permanently delete category <strong>{hardDeleteCategory.path || hardDeleteCategory.name}</strong> (and its subcategories). How should related records be handled?
            </p>
            <div className="space-y-3 mb-5">
              <label className="flex items-center gap-2 cursor-pointer text-theme-dark">
                <input type="radio" name="hardDeleteAction" checked={hardDeleteAction === 'release'} onChange={() => { setHardDeleteAction('release'); setReassignL1Id(''); setReassignL2Id(''); setReassignL3Id(''); }} className="rounded-full border-theme-mid text-theme-orange focus:ring-theme-mid" />
                <span>Release for re-categorization</span>
              </label>
              <label className="flex items-center gap-2 cursor-pointer text-theme-dark">
                <input type="radio" name="hardDeleteAction" checked={hardDeleteAction === 'reassign'} onChange={() => setHardDeleteAction('reassign')} className="rounded-full border-theme-mid text-theme-orange focus:ring-theme-mid" />
                <span>Reassign to another category</span>
              </label>
              {hardDeleteAction === 'reassign' && (
                <div className="pl-6 space-y-2 border-l-2 border-theme-light-gray ml-1">
                  {(() => {
                    const excludeIds = getSelfAndDescendantIds(hardDeleteCategory, list)
                    const l1Opts = l1.filter((c) => !excludeIds.has(c.id))
                    const l2Opts = l2.filter((c) => c.parent_id === reassignL1Id && !excludeIds.has(c.id))
                    const l3Opts = l3.filter((c) => c.parent_id === reassignL2Id && !excludeIds.has(c.id))
                    return (
                      <>
                        <div>
                          <span className="text-xs text-theme-mid block mb-0.5">Category I</span>
                          <select className="border border-theme-light-gray rounded-lg px-2 py-1.5 w-full text-sm text-theme-dark bg-white focus:outline-none focus:ring-1 focus:ring-theme-mid" value={reassignL1Id} onChange={(e) => { setReassignL1Id(e.target.value); setReassignL2Id(''); setReassignL3Id(''); }}>
                            <option value="">Select L1</option>
                            {l1Opts.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                          </select>
                        </div>
                        <div>
                          <span className="text-xs text-theme-mid block mb-0.5">Category II</span>
                          <select className="border border-theme-light-gray rounded-lg px-2 py-1.5 w-full text-sm text-theme-dark bg-white focus:outline-none focus:ring-1 focus:ring-theme-mid disabled:opacity-60" value={reassignL2Id} onChange={(e) => { setReassignL2Id(e.target.value); setReassignL3Id(''); }} disabled={!reassignL1Id}>
                            <option value="">Select L2</option>
                            {l2Opts.map((c) => <option key={c.id} value={c.id}>{c.path || c.name}</option>)}
                          </select>
                        </div>
                        <div>
                          <span className="text-xs text-theme-mid block mb-0.5">Category III</span>
                          <select className="border border-theme-light-gray rounded-lg px-2 py-1.5 w-full text-sm text-theme-dark bg-white focus:outline-none focus:ring-1 focus:ring-theme-mid disabled:opacity-60" value={reassignL3Id} onChange={(e) => setReassignL3Id(e.target.value)} disabled={!reassignL2Id}>
                            <option value="">Select L3</option>
                            {l3Opts.map((c) => <option key={c.id} value={c.id}>{c.path || c.name}</option>)}
                          </select>
                        </div>
                      </>
                    )
                  })()}
                </div>
              )}
            </div>
            <div className="flex justify-end gap-2">
              <button type="button" className="btn-outline px-4 py-2 text-sm font-medium disabled:opacity-50" onClick={closeHardDeleteModal} disabled={hardDeleteSubmitting}>
                Cancel
              </button>
              <button type="button" className="px-4 py-2 rounded-lg font-semibold text-sm text-white bg-theme-red hover:bg-theme-red/90 disabled:opacity-50 disabled:cursor-not-allowed transition-opacity" onClick={handleConfirmHardDelete} disabled={!canConfirmHardDelete || hardDeleteSubmitting}>
                {hardDeleteSubmitting ? 'Processing…' : 'Confirm delete'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
