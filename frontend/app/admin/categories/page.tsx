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
      setError(e instanceof Error ? e.message : '加载失败')
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
        setError('同名一级分类已存在')
        return
      }
      if (!res.ok) throw new Error(data.detail || '创建失败')
      setNewL1Name('')
      fetchCategories()
    } catch (e) {
      setError(e instanceof Error ? e.message : '创建失败')
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
        setError('同名二级分类已存在')
        return
      }
      if (!res.ok) throw new Error(data.detail || '创建失败')
      setNewL2Name('')
      setNewL2ParentId('')
      fetchCategories()
    } catch (e) {
      setError(e instanceof Error ? e.message : '创建失败')
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
        setError('同名三级分类已存在')
        return
      }
      if (!res.ok) throw new Error(data.detail || '创建失败')
      setNewL3Name('')
      setNewL3ParentId('')
      fetchCategories()
    } catch (e) {
      setError(e instanceof Error ? e.message : '创建失败')
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
      setError(e instanceof Error ? e.message : '更新失败')
    }
  }

  const handleDelete = async (id: string) => {
    if (!token || !confirm('确定软删除该分类？')) return
    setError(null)
    try {
      const res = await fetch(`${apiUrl}/api/admin/categories/${id}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` },
      })
      if (!res.ok) throw new Error(await res.text())
      fetchCategories()
    } catch (e) {
      setError(e instanceof Error ? e.message : '删除失败')
    }
  }

  const l1 = list.filter((c) => c.level === 1)
  const l2 = list.filter((c) => c.level === 2)
  const l3 = list.filter((c) => c.level === 3)

  if (!token) return <div className="text-center py-8 text-gray-500">请先登录</div>

  return (
    <div>
      <h2 className="text-lg font-semibold mb-4">Category Management（分类管理）</h2>
      {error && <div className="mb-4 p-2 bg-red-100 text-red-700 rounded text-sm">{error}</div>}
      {loading ? (
        <p className="text-gray-500">加载中...</p>
      ) : (
        <div className="grid grid-cols-3 gap-6">
          {/* Category I (L1) */}
          <div className="bg-white rounded-lg shadow p-4">
            <h3 className="font-medium mb-3">Category I（一级）</h3>
            <div className="mb-3 flex gap-2 items-center">
              <input
                className="border rounded px-2 py-1 flex-1 text-sm"
                placeholder="输入新一级分类名称"
                value={newL1Name}
                onChange={(e) => setNewL1Name(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleCreateL1()}
              />
              <button className="px-2 py-1 bg-green-100 text-green-800 rounded text-sm whitespace-nowrap" onClick={handleCreateL1} disabled={!newL1Name.trim()}>
                新建
              </button>
            </div>
            <ul className="space-y-1 text-sm max-h-80 overflow-y-auto">
              {l1.map((c) => (
                <li key={c.id} className="flex items-center gap-1 group py-0.5">
                  {editingId === c.id ? (
                    <>
                      <input className="border rounded px-1 flex-1" value={editName} onChange={(e) => setEditName(e.target.value)} />
                      <button className="px-1 text-blue-600" onClick={handleUpdate}>保存</button>
                      <button className="px-1 text-gray-500" onClick={() => { setEditingId(null); setEditName(''); }}>取消</button>
                    </>
                  ) : (
                    <>
                      <span className={!c.is_active ? 'text-gray-400' : ''}>{c.name}</span>
                      {!c.is_active && <span className="text-xs text-gray-400">(已禁用)</span>}
                      <button className="opacity-0 group-hover:opacity-100 px-1 text-gray-500" onClick={() => { setEditingId(c.id); setEditName(c.name); }}>编辑</button>
                      {c.is_active && <button className="opacity-0 group-hover:opacity-100 px-1 text-red-600" onClick={() => handleDelete(c.id)}>删除</button>}
                    </>
                  )}
                </li>
              ))}
            </ul>
          </div>

          {/* Category II (L2) */}
          <div className="bg-white rounded-lg shadow p-4">
            <h3 className="font-medium mb-3">Category II（二级）</h3>
            <div className="mb-3 space-y-2">
              <select
                className="border rounded px-2 py-1 w-full text-sm"
                value={newL2ParentId}
                onChange={(e) => setNewL2ParentId(e.target.value)}
              >
                <option value="">选择父级 (L1)</option>
                {l1.filter((c) => c.is_active).map((c) => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
              </select>
              <div className="flex gap-2 items-center">
                <input
                  className="border rounded px-2 py-1 flex-1 text-sm"
                  placeholder="输入新二级分类名称"
                  value={newL2Name}
                  onChange={(e) => setNewL2Name(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleCreateL2()}
                />
                <button className="px-2 py-1 bg-green-100 text-green-800 rounded text-sm whitespace-nowrap" onClick={handleCreateL2} disabled={!newL2Name.trim() || !newL2ParentId}>
                  新建
                </button>
              </div>
            </div>
            <ul className="space-y-1 text-sm max-h-80 overflow-y-auto">
              {l2.map((c) => (
                <li key={c.id} className="flex items-center gap-1 group py-0.5">
                  {editingId === c.id ? (
                    <>
                      <input className="border rounded px-1 flex-1" value={editName} onChange={(e) => setEditName(e.target.value)} />
                      <button className="px-1 text-blue-600" onClick={handleUpdate}>保存</button>
                      <button className="px-1 text-gray-500" onClick={() => { setEditingId(null); setEditName(''); }}>取消</button>
                    </>
                  ) : (
                    <>
                      <span className={!c.is_active ? 'text-gray-400' : ''}>{c.path || c.name}</span>
                      {!c.is_active && <span className="text-xs text-gray-400">(已禁用)</span>}
                      <button className="opacity-0 group-hover:opacity-100 px-1 text-gray-500" onClick={() => { setEditingId(c.id); setEditName(c.name); }}>编辑</button>
                      {c.is_active && <button className="opacity-0 group-hover:opacity-100 px-1 text-red-600" onClick={() => handleDelete(c.id)}>删除</button>}
                    </>
                  )}
                </li>
              ))}
            </ul>
          </div>

          {/* Category III (L3) */}
          <div className="bg-white rounded-lg shadow p-4">
            <h3 className="font-medium mb-3">Category III（三级）</h3>
            <div className="mb-3 space-y-2">
              <select
                className="border rounded px-2 py-1 w-full text-sm"
                value={newL3ParentId}
                onChange={(e) => setNewL3ParentId(e.target.value)}
              >
                <option value="">选择父级 (L2)</option>
                {l2.filter((c) => c.is_active).map((c) => (
                  <option key={c.id} value={c.id}>{c.path || c.name}</option>
                ))}
              </select>
              <div className="flex gap-2 items-center">
                <input
                  className="border rounded px-2 py-1 flex-1 text-sm"
                  placeholder="输入新三级分类名称"
                  value={newL3Name}
                  onChange={(e) => setNewL3Name(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleCreateL3()}
                />
                <button className="px-2 py-1 bg-green-100 text-green-800 rounded text-sm whitespace-nowrap" onClick={handleCreateL3} disabled={!newL3Name.trim() || !newL3ParentId}>
                  新建
                </button>
              </div>
            </div>
            <ul className="space-y-1 text-sm max-h-80 overflow-y-auto">
              {l3.map((c) => (
                <li key={c.id} className="flex items-center gap-1 group py-0.5">
                  {editingId === c.id ? (
                    <>
                      <input className="border rounded px-1 flex-1" value={editName} onChange={(e) => setEditName(e.target.value)} />
                      <button className="px-1 text-blue-600" onClick={handleUpdate}>保存</button>
                      <button className="px-1 text-gray-500" onClick={() => { setEditingId(null); setEditName(''); }}>取消</button>
                    </>
                  ) : (
                    <>
                      <span className={!c.is_active ? 'text-gray-400' : ''}>{c.path || c.name}</span>
                      {!c.is_active && <span className="text-xs text-gray-400">(已禁用)</span>}
                      <button className="opacity-0 group-hover:opacity-100 px-1 text-gray-500" onClick={() => { setEditingId(c.id); setEditName(c.name); }}>编辑</button>
                      {c.is_active && <button className="opacity-0 group-hover:opacity-100 px-1 text-red-600" onClick={() => handleDelete(c.id)}>删除</button>}
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
