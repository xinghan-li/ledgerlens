'use client'

import { useEffect, useState } from 'react'
import { getFirebaseAuth } from '@/lib/firebase'
import { onAuthStateChanged } from 'firebase/auth'

const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

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

  useEffect(() => {
    const auth = getFirebaseAuth()
    const unsubscribe = onAuthStateChanged(auth, async (user) => {
      setToken(user ? await user.getIdToken() : null)
    })
    return () => unsubscribe()
  }, [])

  const fetchCategories = async () => {
    if (!token) return
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`${apiUrl}/api/admin/categories?active_only=false`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (!res.ok) throw new Error(await res.text())
      const data = await res.json()
      setList(data.data || [])
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (token) fetchCategories()
  }, [token])

  const handleCreateL1 = async () => {
    if (!token || !newL1Name.trim()) return
    setError(null)
    try {
      const res = await fetch(`${apiUrl}/api/admin/categories`, {
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
      fetchCategories()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Create failed')
    }
  }

  const handleCreateL2 = async () => {
    if (!token || !newL2Name.trim() || !newL2ParentId) return
    setError(null)
    try {
      const res = await fetch(`${apiUrl}/api/admin/categories`, {
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
      setNewL2ParentId('')
      fetchCategories()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Create failed')
    }
  }

  const handleCreateL3 = async () => {
    if (!token || !newL3Name.trim() || !newL3ParentId) return
    setError(null)
    try {
      const res = await fetch(`${apiUrl}/api/admin/categories`, {
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
      setNewL3ParentId('')
      fetchCategories()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Create failed')
    }
  }

  const handleUpdate = async () => {
    if (!token || !editingId || !editName.trim()) return
    setError(null)
    try {
      const res = await fetch(`${apiUrl}/api/admin/categories/${editingId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ name: editName.trim() }),
      })
      if (!res.ok) throw new Error(await res.text())
      setEditingId(null)
      setEditName('')
      fetchCategories()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Update failed')
    }
  }

  const handleDelete = async (id: string) => {
    if (!token || !confirm('Soft-delete this category?')) return
    setError(null)
    try {
      const res = await fetch(`${apiUrl}/api/admin/categories/${id}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` },
      })
      if (!res.ok) throw new Error(await res.text())
      fetchCategories()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Delete failed')
    }
  }

  const l1 = list.filter((c) => c.level === 1)
  const l2 = list.filter((c) => c.level === 2)
  const l3 = list.filter((c) => c.level === 3)

  if (!token) return <div className="text-center py-8 text-gray-500">Please sign in first.</div>

  return (
    <div>
      <h2 className="text-lg font-semibold mb-4">Category Management</h2>
      {error && <div className="mb-4 p-2 bg-red-100 text-red-700 rounded text-sm">{error}</div>}
      {loading ? (
        <p className="text-gray-500">Loading…</p>
      ) : (
        <div className="grid grid-cols-3 gap-6">
          {/* Category I (L1) */}
          <div className="bg-white rounded-lg shadow p-4">
            <h3 className="font-medium mb-3">Category I</h3>
            <div className="mb-3 flex gap-2 items-center">
              <input
                className="border rounded px-2 py-1 flex-1 text-sm"
                placeholder="New L1 category name"
                value={newL1Name}
                onChange={(e) => setNewL1Name(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleCreateL1()}
              />
              <button className="px-2 py-1 bg-green-100 text-green-800 rounded text-sm whitespace-nowrap" onClick={handleCreateL1} disabled={!newL1Name.trim()}>
                Add
              </button>
            </div>
            <ul className="space-y-1 text-sm max-h-80 overflow-y-auto">
              {l1.map((c) => (
                <li key={c.id} className="flex items-center gap-1 group py-0.5">
                  {editingId === c.id ? (
                    <>
                      <input className="border rounded px-1 flex-1" value={editName} onChange={(e) => setEditName(e.target.value)} />
                      <button className="px-1 text-blue-600" onClick={handleUpdate}>Save</button>
                      <button className="px-1 text-gray-500" onClick={() => { setEditingId(null); setEditName(''); }}>Cancel</button>
                    </>
                  ) : (
                    <>
                      <span className={!c.is_active ? 'text-gray-400' : ''}>{c.name}</span>
                      {!c.is_active && <span className="text-xs text-gray-400">(disabled)</span>}
                      <button className="opacity-0 group-hover:opacity-100 px-1 text-gray-500" onClick={() => { setEditingId(c.id); setEditName(c.name); }}>Edit</button>
                      {c.is_active && <button className="opacity-0 group-hover:opacity-100 px-1 text-red-600" onClick={() => handleDelete(c.id)}>Delete</button>}
                    </>
                  )}
                </li>
              ))}
            </ul>
          </div>

          {/* Category II (L2) */}
          <div className="bg-white rounded-lg shadow p-4">
            <h3 className="font-medium mb-3">Category II</h3>
            <div className="mb-3 space-y-2">
              <select
                className="border rounded px-2 py-1 w-full text-sm"
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
                  className="border rounded px-2 py-1 flex-1 text-sm"
                  placeholder="New L2 category name"
                  value={newL2Name}
                  onChange={(e) => setNewL2Name(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleCreateL2()}
                />
                <button className="px-2 py-1 bg-green-100 text-green-800 rounded text-sm whitespace-nowrap" onClick={handleCreateL2} disabled={!newL2Name.trim() || !newL2ParentId}>
                  Add
                </button>
              </div>
            </div>
            <ul className="space-y-1 text-sm max-h-80 overflow-y-auto">
              {l2.map((c) => (
                <li key={c.id} className="flex items-center gap-1 group py-0.5">
                  {editingId === c.id ? (
                    <>
                      <input className="border rounded px-1 flex-1" value={editName} onChange={(e) => setEditName(e.target.value)} />
                      <button className="px-1 text-blue-600" onClick={handleUpdate}>Save</button>
                      <button className="px-1 text-gray-500" onClick={() => { setEditingId(null); setEditName(''); }}>Cancel</button>
                    </>
                  ) : (
                    <>
                      <span className={!c.is_active ? 'text-gray-400' : ''}>{c.path || c.name}</span>
                      {!c.is_active && <span className="text-xs text-gray-400">(disabled)</span>}
                      <button className="opacity-0 group-hover:opacity-100 px-1 text-gray-500" onClick={() => { setEditingId(c.id); setEditName(c.name); }}>Edit</button>
                      {c.is_active && <button className="opacity-0 group-hover:opacity-100 px-1 text-red-600" onClick={() => handleDelete(c.id)}>Delete</button>}
                    </>
                  )}
                </li>
              ))}
            </ul>
          </div>

          {/* Category III (L3) */}
          <div className="bg-white rounded-lg shadow p-4">
            <h3 className="font-medium mb-3">Category III</h3>
            <div className="mb-3 space-y-2">
              <select
                className="border rounded px-2 py-1 w-full text-sm"
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
                  className="border rounded px-2 py-1 flex-1 text-sm"
                  placeholder="New L3 category name"
                  value={newL3Name}
                  onChange={(e) => setNewL3Name(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleCreateL3()}
                />
                <button className="px-2 py-1 bg-green-100 text-green-800 rounded text-sm whitespace-nowrap" onClick={handleCreateL3} disabled={!newL3Name.trim() || !newL3ParentId}>
                  Add
                </button>
              </div>
            </div>
            <ul className="space-y-1 text-sm max-h-80 overflow-y-auto">
              {l3.map((c) => (
                <li key={c.id} className="flex items-center gap-1 group py-0.5">
                  {editingId === c.id ? (
                    <>
                      <input className="border rounded px-1 flex-1" value={editName} onChange={(e) => setEditName(e.target.value)} />
                      <button className="px-1 text-blue-600" onClick={handleUpdate}>Save</button>
                      <button className="px-1 text-gray-500" onClick={() => { setEditingId(null); setEditName(''); }}>Cancel</button>
                    </>
                  ) : (
                    <>
                      <span className={!c.is_active ? 'text-gray-400' : ''}>{c.path || c.name}</span>
                      {!c.is_active && <span className="text-xs text-gray-400">(disabled)</span>}
                      <button className="opacity-0 group-hover:opacity-100 px-1 text-gray-500" onClick={() => { setEditingId(c.id); setEditName(c.name); }}>Edit</button>
                      {c.is_active && <button className="opacity-0 group-hover:opacity-100 px-1 text-red-600" onClick={() => handleDelete(c.id)}>Delete</button>}
                    </>
                  )}
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </div>
  )
}
